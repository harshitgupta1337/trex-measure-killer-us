#!/usr/bin/python
import sys, getopt
import argparse;
""" 
Sample API application, 
Connect to TRex 
Send UDP packet in specific length 
Each direction has its own IP range
Compare  Rx-pkts to TX-pkts assuming ports are loopback

"""

import time
import stl_path
from trex_stl_lib.api import *

H_VER = "trex-x v0.1 "

class t_global(object):
     args=None;


import time
import json
import string

def generate_payload(length):
    word = ''
    alphabet_size = len(string.letters)
    for i in range(length):
        word += string.letters[(i % alphabet_size)]
    return word

# simple packet creation
def create_pkt (frame_size = 9000, direction=0):

    ip_range = {'src': {'start': "16.0.0.1", 'end': "16.0.0.254"},
                'dst': {'start': "48.0.0.1",  'end': "48.0.254.254"}}

    if (direction == 0):
        src = ip_range['src']
        dst = ip_range['dst']
    else:
        src = ip_range['dst']
        dst = ip_range['src']

    vm = [
        # src
        STLVmFlowVar(name="src",min_value=src['start'],max_value=src['end'],size=4,op="inc"),
        STLVmWrFlowVar(fv_name="src",pkt_offset= "IP.src"),

        # dst
        STLVmFlowVar(name="dst",min_value=dst['start'],max_value=dst['end'],size=4,op="inc"),
        STLVmWrFlowVar(fv_name="dst",pkt_offset= "IP.dst"),

        # checksum
        STLVmFixIpv4(offset = "IP")#,

        ]

    pkt_base  = Ether()/Dot1Q(vlan = 110)/IP()/UDP()
    #pkt_base  = Ether(src="00:00:00:00:00:01",dst="00:00:00:00:00:02")/IP()/UDP(dport=12,sport=1025)
    pyld_size = frame_size - len(pkt_base);
    pkt_pyld   = generate_payload(pyld_size) 

    return STLPktBuilder(pkt = pkt_base/pkt_pyld,
                         vm  = vm)

def simple_burst ( outfile, ports, low_tput, high_tput, levels, duration = 10, frame_size = 9000, speed = '1gbps'):
   
    if (frame_size < 60):
        frame_size = 60

    pkt_dir_0 = create_pkt (frame_size, 0) 
    latency_pkt_dir_0 = create_pkt (frame_size+16, 0) 

#    pkt_dir_1 = create_pkt (frame_size, 1) 

    # create client
    c = STLClient(server = t_global.args.ip)

    passed = True

    try:
        # turn this on for some information
        #c.set_verbose("high")

        # create two streams
        s1 = STLStream(packet = pkt_dir_0,
                       mode = STLTXCont(pps = 100))

        lat_stream = STLStream(packet = latency_pkt_dir_0,
                               mode = STLTXCont(pps=1000),
                               flow_stats = STLFlowLatencyStats(pg_id = 12))

        # second stream with a phase of 1ms (inter stream gap)
 #       s2 = STLStream(packet = pkt_dir_1,
 #                      isg = 1000,
 #                      mode = STLTXCont(pps = 100))

        if t_global.args.debug:
            STLStream.dump_to_yaml ("example.yaml", [s1]) # export to YAML so you can run it on simulator ./stl-sim -f example.yaml -o o.pcap 

        # connect to server
        c.connect()

        # prepare our ports (my machine has 0 <--> 1 with static route)
        c.reset(ports = [0, 1])

        # add both streams to ports
        c.add_streams(s1, ports = [0])
        c.add_streams(lat_stream, ports = [0])
#        c.add_streams(s2, ports = [1])

        # clear the stats before injecting
        c.clear_stats()

        ramp_up_time = 15 #seconds
        ramp_down_time = 15 #seconds

        traffic_bws = []
        per_level_diff = (high_tput - low_tput)/float(levels)
        for l in range(levels):
            tput = l*per_level_diff + low_tput
            traffic_bws.append(int(tput))
        traffic_bws.append(int(high_tput))
        total_flow_time = ramp_up_time + ramp_down_time + duration*(levels*2 + 1)

        f = open(outfile, "w")

        #traffic_bws = [1500, 2000, 2500, 3000, 3500, 4000, 4500]    # in Mbps
        # choose rate and start traffic for 10 seconds on 5 mpps
        print("Running {0} on ports 0, 1 for 10 seconds, UDP {1}...".format(speed,frame_size+4))
        c.start(ports = ports, mult = "%dmbps"%low_tput, duration = total_flow_time)

        sleep_time = 0
        for bw in traffic_bws:
            while sleep_time < duration:
                time.sleep(0.2)
                time_ms = int(round(time.time() * 1000))
                data = {}
                data["ts"] = time_ms
                data["stats"] = c.get_stats()
                f.write(json.dumps(data))
                f.write("\n")
                sleep_time += 0.2
            sleep_time = 0
            c.update_line("--port 0 -m %dmbps"%bw)

        sleep_time = 0
        for i in range(len(traffic_bws)):
            idx = len(traffic_bws)-1-i
            bw = traffic_bws[idx]
            while sleep_time < duration:
                time.sleep(0.2)
                time_ms = int(round(time.time() * 1000))
                data = {}
                data["ts"] = time_ms
                data["stats"] = c.get_stats()
                f.write(json.dumps(data))
                f.write("\n")
                sleep_time += 0.2
            sleep_time = 0
            c.update_line("--port 0 -m %dmbps"%bw)

        # block until done
        c.wait_on_traffic(ports = [0])
        f.close()

    except STLError as e:
        passed = False
        print(e)

    finally:
        c.disconnect()

    if passed:
        print("\nPASSED\n")
    else:
        print("\nFAILED\n")

def process_options ():
    parser = argparse.ArgumentParser(usage=""" 
    connect to TRex and send burst of packets

    examples

     stl_run_udp_simple.py -s 9001  

     stl_run_udp_simple.py -s 9000 -d 2     

     stl_run_udp_simple.py -s 3000 -d 3 -m 10mbps

     stl_run_udp_simple.py -s 3000 -d 3 -m 10mbps --debug

     then run the simulator on the output 
       ./stl-sim -f example.yaml -o a.pcap  ==> a.pcap include the packet

    """,
    description="example for TRex api",
    epilog=" written by hhaim");

    parser.add_argument("-s", "--frame-size", 
                        dest="frame_size",
                        help='L2 frame size in bytes without FCS',
                        default=60,
                        type = int,
                        )

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


    parser.add_argument('-P','--ports', 
                        dest='ports',
                        help='Which ports should be involved',
                        nargs="*",
                        type=int
                        )

    parser.add_argument('-H','--high-tput', 
                        dest='high_tput',
                        help='high throughput (mbps)',
                        default="1024",
                        type=int
                        )

    parser.add_argument('-l','--low-tput', 
                        dest='low_tput',
                        help='low throughput (mbps)',
                        default="1",
                        type=int
                        )

    parser.add_argument('-L','--levels', 
                        dest='levels',
                        help='Number of levels between low and high throughput',
                        default="16",
                        type=int
                        )

    parser.add_argument('-m','--multiplier', 
                        dest='mul',
                        help='speed in gbps/pps for example 1gbps, 1mbps, 1mpps ',
                        default="1mbps"
                        )

    parser.add_argument('--debug', 
                        action='store_true',
                        help='see debug into ')

    parser.add_argument('--version', action='version',
                        version=H_VER )

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

    t_global.args = parser.parse_args();
    print(t_global.args)



def main():
    process_options ()
    simple_burst(duration = t_global.args.duration,  
                 frame_size = t_global.args.frame_size,
                 speed = t_global.args.mul,
                 ports = t_global.args.ports,
                 low_tput = t_global.args.low_tput,
                 high_tput = t_global.args.high_tput,
                 levels = t_global.args.levels,
                 outfile = t_global.args.outfile
                 )

if __name__ == "__main__":
    main()

