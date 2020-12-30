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

def create_steps(outfile, bidir, low_tput, high_tput, pps, levels, profile, duration = 10, vlan=None):
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
    ramp_down_time = 15 #seconds

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
    total_flow_time = ramp_up_time + ramp_down_time + duration*(levels*2 + 1)

    f = open(outfile, "w")

    # choose rate and start traffic for 10 seconds on 5 mpps
    mult = "%d%s"%(low_tput, unit)
    print ("Enforcing mult %s on directions %s"%(mult, str(directions)))
    client.start(ports = directions, mult = mult, duration = total_flow_time)

    sleep_step_secs = 2
    sleep_time = 0
    for bw in traffic_bws:
        while sleep_time < duration:
            client.clear_stats()
            time.sleep(sleep_step_secs)
            time_ms = int(round(time.time() * 1000))
            data = {}
            data["ts"] = time_ms
            data["stats"] = client.get_stats()
            f.write(json.dumps(data))
            f.write("\n")
            sleep_time += sleep_step_secs
        sleep_time = 0
        mult = "%d%s"%(bw, unit)
        print ("Enforcing mult %s on directions %s"%(mult, str(directions)))
        for d in directions:
            client.update_line("--port %d -m %s"%(d, mult))

    sleep_time = 0
    for i in range(len(traffic_bws)):
        idx = len(traffic_bws)-1-i
        bw = traffic_bws[idx]
        while sleep_time < duration:
            client.clear_stats()
            time.sleep(sleep_step_secs)
            time_ms = int(round(time.time() * 1000))
            data = {}
            data["ts"] = time_ms
            data["stats"] = client.get_stats()
            f.write(json.dumps(data))
            f.write("\n")
            sleep_time += sleep_step_secs
        sleep_time = 0
        mult = "%d%s"%(bw, unit)
        print ("Enforcing mult %s on directions %s"%(mult, str(directions)))
        for d in directions:
            client.update_line("--port %d -m %s"%(d, mult))

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

    parser.add_argument("--ip", 
                        dest="ip",
                        help='remote trex ip default local',
                        default="127.0.0.1",
                        type = str
                        )

    parser.add_argument('-d','--duration-per-level', 
                        dest='duration',
                        help='duration in second ',
                        default=10,
                        type = int,
                        )

    parser.add_argument('-H','--high-tput', 
                        dest='high_tput',
                        help='high throughput',
                        default="1024",
                        type=int
                        )

    parser.add_argument('-l','--low-tput', 
                        dest='low_tput',
                        help='low throughput ',
                        default="1",
                        type=int
                        )

    parser.add_argument('-L','--levels', 
                        dest='levels',
                        help='Number of levels between low and high throughput',
                        default="16",
                        type=int
                        )

    parser.add_argument('-O','--out-file', 
                        dest='outfile',
                        help='Output file to write the stats to',
                        default="/tmp/test.out"
                        )
    parser.add_argument("--bidirectional",
            dest="bidir",
            help='Generate traffic in both directions',
            action='store_true'
            )

    parser.add_argument("--vlan",
        dest="vlan",
        help='VLAN ID',
        default=None,
        type = int
        )
    parser.add_argument("--imix-profile",
        dest="imix_profile",
        help='IMIX profile path',
        type = str,
        required = True
        )

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
                 profile = profile
                 )

#    outfile, bidir, low_rate, high_rate, pps, levels, duration = 10, vlan=None

if __name__ == "__main__":
    main()

