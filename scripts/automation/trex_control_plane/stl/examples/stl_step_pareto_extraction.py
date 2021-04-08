#!/usr/bin/python
import sys, getopt
import argparse;
import time
import stl_path
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

def create_steps(outfile, bidir, low_tput, high_tput, pps, levels, profile, freqs, core, dut, vlan=None, duration = 10):
    client = STLClient(server=t_global.args.ip)
    client.connect()
    if bidir:
        directions = [0,1]
    else:
        directions = [0]
    client.reset(ports=directions)
    client.set_port_attr(ports = directions, promiscuous = False)

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

    traffic_bws = []
    per_level_diff = (high_tput - low_tput)/float(levels)
    for l in range(levels):
        tput = l*per_level_diff + low_tput
        traffic_bws.append(int(tput))
    traffic_bws.append(int(high_tput))
    if pps:
        unit = "kpps"
    else:
        unit = "mbps"

    print (traffic_bws)
    print (unit)
    init_sleep = 15
    total_flow_time = 2*ramp_up_time + (duration+init_sleep)*(levels+1)*len(freqs)
    print ("Total flow time = %d"%total_flow_time)

    f = open(outfile, "w")

    # choose rate and start traffic for 10 seconds on 5 mpps
    mult = "%d%s"%(low_tput, unit)
    print ("Enforcing mult %s on directions %s"%(mult, str(directions)))
    client.start(ports = directions, mult = mult, duration = total_flow_time)
    time.sleep(ramp_up_time)

    client.clear_stats()

    for bw in traffic_bws:
        mult = "%d%s"%(bw, unit)
        print ("Enforcing mult %s on directions %s"%(mult, str(directions)))
        for d in directions:
            client.update_line("--port %d -m %s"%(d, mult))

        for freq in freqs:
            freq_str = "%.1f"%freq

            # Set the frequency of the DUT core at this
            print ("Setting CPU frequency of core %s on DUT %s to %s"%(core, dut, freq_str))
            os.system("/home/harshit/dpdkpowermgmt/monitor_scripts/utilization/utils/set_dut_core_freq.sh %s %s %s"%(dut, core, freq_str))


            data = {}

            time.sleep(init_sleep)
            client.clear_stats()
            data["init_stats"] = client.get_stats()

            time.sleep(duration)

            time_ms = int(round(time.time() * 1000))
            data["ts"] = time_ms
            data["final_stats"] = client.get_stats()
            data["bw"] = bw
            data["freq"] = freq
            f.write(json.dumps(data))
            f.write("\n")

    # block until done
    client.wait_on_traffic(ports = directions)

    f.close()

    client.disconnect()

    if passed:
        print("\nPASSED\n")
    else:
        print("\nFAILED\n")

def process_options ():
    parser = argparse.ArgumentParser();
    parser.add_argument("--ip", dest="ip", help='remote trex ip default local', default="127.0.0.1", type = str)
    parser.add_argument('-d','--duration-per-level',dest='duration',help='duration in second ',default=10,type = int,)
    parser.add_argument('-H','--high-tput', dest='high_tput',help='high throughput',default="1024",type=int)
    parser.add_argument('-l','--low-tput', dest='low_tput',help='low throughput ',default="1",type=int)
    parser.add_argument('-L','--levels', dest='levels',help='Number of levels between low and high throughput',default="16",type=int)
    parser.add_argument('-O','--out-file', dest='outfile',help='Output file to write the stats to',default="/tmp/test.out")
    parser.add_argument("--bidirectional",dest="bidir",help='Generate traffic in both directions',action='store_true')
    parser.add_argument("--vlan",dest="vlan",help='VLAN ID',default=None,type = int)
    parser.add_argument("--imix-profile",dest="imix_profile",help='IMIX profile path',type = str,required = True)
    parser.add_argument("--core",dest="core",help='CPU core running packet processing',type = str,required = True)
    parser.add_argument("--dut",dest="dut",help='Hostname or IP of DUT server',type = str,required = True)
    parser.add_argument("--freqs",dest="freqs",help='Allowed core frequencies',type = float,nargs="*",required = True)

    t_global.args = parser.parse_args();
    print(t_global.args)

def main():
    process_options ()
    profile = read_profile(t_global.args.imix_profile)
    create_steps(duration = t_global.args.duration,  
                 low_tput = t_global.args.low_tput,
                 high_tput = t_global.args.high_tput,
                 levels = t_global.args.levels,
                 outfile = t_global.args.outfile,
                 bidir=t_global.args.bidir,
                 pps=True,
                 vlan = t_global.args.vlan,
                 profile = profile,
                 freqs = t_global.args.freqs,
                 core=t_global.args.core,
                 dut=t_global.args.dut
                 )

if __name__ == "__main__":
    main()

