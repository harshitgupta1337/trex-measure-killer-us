#!/usr/bin/python
import sys, getopt
import argparse;
import time
import stl_path
import yaml
from trex_stl_lib.api import *

H_VER = "trex-x v0.1 "

class t_global(object):
     args=None;

import json
import string

ip_range = {'src': {'start': "16.0.0.1", 'end': "16.0.0.254"},
                    'dst': {'start': "48.0.0.1",  'end': "48.0.0.254"}}

def read_profile(profilePath):
    x = None
    with open(profilePath, "r") as f:
        x = json.load(f)
    f.close()
    return x

def get_vm(direction):
    if direction == 0:
        src = ip_range["src"]
        dst = ip_range["dst"]
    else:
        src = ip_range["dst"]
        dst = ip_range["src"]
    vm = STLVM()
    # define two vars (src and dst)
    vm.var(name="src",min_value=src['start'],max_value=src['end'],size=4,op="inc")
    vm.var(name="dst",min_value=dst['start'],max_value=dst['end'],size=4,op="inc")
    # write them
    vm.write(fv_name="src",pkt_offset= "IP.src")
    vm.write(fv_name="dst",pkt_offset= "IP.dst")
    # fix checksum
    vm.fix_chksum()
    return vm

def generate_payload(length):
    word = ''
    alphabet_size = len(string.letters)
    for i in range(length):
        word += string.letters[(i % alphabet_size)]
    return word

def create_pkt (size, vm, vlan):
    # Create base packet and pad it to size
    if vlan:
        base_pkt = Ether()/Dot1Q(vlan = vlan)/IP()
    else:
        base_pkt = Ether()/IP()
    pad = max(0, size - len(base_pkt)) * 'x'
    pkt = STLPktBuilder(pkt = base_pkt/pad, vm = vm)
    return pkt

def get_steps (min_freqs_file):
    with open(min_freqs_file) as f:
        d = yaml.load(f)
    steps = sorted(d["freqs"], key = lambda x : x["bw"])
    return steps

def create_steps(outfile, bidir, pps, profile, aggr_metrics, no_scale_down, min_freqs_file, core, dut, duration = 10, vlan=None):
    client = STLClient(server=t_global.args.ip)
    client.connect()
    if bidir:
        directions = [0,1]
    else:
        directions = [0]
    client.reset(ports=directions)
    client.set_port_attr(ports = directions, promiscuous = False)

    steps = get_steps(min_freqs_file)
    low_freq = steps[0]["freq"]
    freq_str = "%.1f"%low_freq
    print ("Setting CPU frequency of core %s on DUT %s to %s"%(core, dut, freq_str))
    os.system("/home/harshit/dpdkpowermgmt/monitor_scripts/utilization/utils/set_dut_core_freq.sh %s %s %s"%(dut, core, freq_str))

    passed = True

    latency_pgids = []
    for direction in directions:
        vm = get_vm(direction)
        streams = []
        total_pps = 1000
        for i in range(len(profile)):
            x = profile[i]
            pps = total_pps * x['ratio']
            pkt = create_pkt(x["size"], vm, vlan)
            streams.append(STLStream(packet=pkt, mode=STLTXCont(pps = pps), isg=x['isg']))
        latency_pgid = 12+direction
        lat_stream = STLStream(packet = create_pkt(256, vm, vlan), mode = STLTXCont(pps=1000), flow_stats = STLFlowLatencyStats(pg_id = latency_pgid))
        streams.append(lat_stream)
        latency_pgids.append(latency_pgid)
        client.add_streams(streams, ports=[direction])

    client.clear_stats()

    ramp_up_time = 15 #seconds

    levels = len(steps)
    if pps:
        unit = "kpps"
    else:
        unit = "mbps"

    if no_scale_down:
        total_flow_time = ramp_up_time + duration*levels
    else:
        total_flow_time = ramp_up_time + duration*(levels*2 + 1)

    f = open(outfile, "w")

    # choose rate and start traffic for 10 seconds on 5 mpps
    mult = "%d%s"%(steps[0]["bw"], unit)
    print ("Enforcing mult %s on directions %s"%(mult, str(directions)))
    client.start(ports = directions, mult = mult, duration = total_flow_time)
    time.sleep(ramp_up_time)

    curr_freq = low_freq  

    client.clear_stats()

    sleep_step_secs = 5
    sleep_time = 0
    for step in steps:
        # Set the correct frequency for this step
        new_freq = step["freq"]
        if curr_freq != new_freq:
            freq_str = "%.1f"%new_freq
            print ("Setting CPU frequency of core %s on DUT %s to %s"%(core, dut, freq_str))
            os.system("/home/harshit/dpdkpowermgmt/monitor_scripts/utilization/utils/set_dut_core_freq.sh %s %s %s"%(dut, core, freq_str))
        curr_freq = new_freq

        sleep_time = 0
        bw = step["bw"]
        mult = "%d%s"%(bw, unit)
        print ("Enforcing mult %s on directions %s"%(mult, str(directions)))
        for d in directions:
            client.update_line("--port %d -m %s"%(d, mult))

        # Now waiting for per-step duration
        while sleep_time < duration:
            if not aggr_metrics:
                client.clear_stats()
                data = {}
                data["init_stats"] = client.get_stats()

            time.sleep(sleep_step_secs)
            sleep_time += sleep_step_secs

            if not aggr_metrics:
                time_ms = int(round(time.time() * 1000))
                data["ts"] = time_ms
                data["final_stats"] = client.get_stats()
                data["bw"] = bw
                data["freq"] = curr_freq
                f.write(json.dumps(data))
                f.write("\n")

    if not no_scale_down:
        sleep_time = 0
        for i in range(len(steps)):
            idx = len(steps)-1-i
            step = steps[idx]
            bw = step["bw"]

            # Set the correct frequency for this step
            new_freq = step["freq"]
            if curr_freq != new_freq:
                freq_str = "%.1f"%new_freq
                print ("Setting CPU frequency of core %s on DUT %s to %s"%(core, dut, freq_str))
                os.system("/home/harshit/dpdkpowermgmt/monitor_scripts/utilization/utils/set_dut_core_freq.sh %s %s %s"%(dut, core, freq_str))
            curr_freq = new_freq

            sleep_time = 0
            mult = "%d%s"%(bw, unit)
            print ("Enforcing mult %s on directions %s"%(mult, str(directions)))
            for d in directions:
                client.update_line("--port %d -m %s"%(d, mult))

            # now waiting for per step duration
            while sleep_time < duration:
                if not aggr_metrics:
                    client.clear_stats()
                    data = {}
                    data["init_stats"] = client.get_stats()
    
                time.sleep(sleep_step_secs)
                sleep_time += sleep_step_secs
    
                if not aggr_metrics:
                    time_ms = int(round(time.time() * 1000))
                    data["ts"] = time_ms
                    data["final_stats"] = client.get_stats()
                    data["bw"] = bw
                    data["freq"] = curr_freq
                    f.write(json.dumps(data))
                    f.write("\n")

    # block until done
    client.wait_on_traffic(ports = directions)

    if aggr_metrics:
        time_ms = int(round(time.time() * 1000))
        data = {}
        data["ts"] = time_ms
        data["stats"] = client.get_stats()
        data["bw"] = bw
        f.write(json.dumps(data))
        f.write("\n")

    f.close()

    client.disconnect()

    if passed:
        print("\nPASSED\n")
    else:
        print("\nFAILED\n")

def process_options ():
    parser = argparse.ArgumentParser();

    parser.add_argument("--ip", dest="ip",help='remote trex ip default local',default="127.0.0.1",type = str)
    parser.add_argument('-d','--duration-per-level',dest='duration',help='duration in second ',default=10,type = int,)
    parser.add_argument('-M','--min-freqs',dest='min_freqs',help='YAML file containing info about min freqs for each BW step',required=True)
    parser.add_argument('-O','--out-file',dest='outfile',help='Output file to write the stats to',default="/tmp/test.out")
    parser.add_argument("--aggr-metrics",dest="aggr_metrics",help='Aggregate metrics over the entire run',action='store_true',default=False)
    parser.add_argument("--no-scale-down",dest="no_scale_down",help='Add this flag to prevent traffic rate from going down after peak. Cuts off traffic at peak.',action='store_true',default=False)
    parser.add_argument("--bidirectional",dest="bidir",help='Generate traffic in both directions',action='store_true')
    parser.add_argument("--vlan",dest="vlan",help='VLAN ID',default=None,type = int)
    parser.add_argument("--imix-profile",dest="imix_profile",help='IMIX profile path',type = str,required = True)

    parser.add_argument("--core",dest="core",help='CPU core running packet processing',type = str,required = True)
    parser.add_argument("--dut",dest="dut",help='Hostname or IP of DUT server',type = str,required = True)

    t_global.args = parser.parse_args();
    print(t_global.args)

def main():
    process_options ()
    profile = read_profile(t_global.args.imix_profile)
    create_steps(duration = t_global.args.duration,  
                 min_freqs_file = t_global.args.min_freqs,
                 outfile = t_global.args.outfile,
                 bidir=t_global.args.bidir,
                 pps=True,
                 vlan = t_global.args.vlan,
                 profile = profile,
                 aggr_metrics=t_global.args.aggr_metrics,
                 no_scale_down=t_global.args.no_scale_down,
                 dut=t_global.args.dut,
                 core=t_global.args.core
                 )

if __name__ == "__main__":
    main()

