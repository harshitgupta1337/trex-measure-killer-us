#!/usr/bin/python
import sys, getopt
import argparse;
import time
import stl_path
from trex_stl_lib.api import *

H_VER = "trex-x v0.1 "

class t_global(object):
     args=None;


import time
import json
import string

ip_range = {'src': {'start': "16.0.0.1", 'end': "16.0.0.254"},
            'dst': {'start': "48.0.0.1",  'end': "48.0.0.254"}}


imix_table = [{'size': 90, 'isg':0, 'ratio':1.0}]

def create_pkt (size, vm, vlan):
    # Create base packet and pad it to size
    if vlan:
        base_pkt = Ether()/Dot1Q(vlan = vlan)/IP()
    else:
        base_pkt = Ether()/IP()
    pad = max(0, size - len(base_pkt)) * 'x'
    pkt = STLPktBuilder(pkt = base_pkt/pad,
                        vm = vm)
    return pkt

def single_run(client, streams, rate, duration, pps=False, directions=[0,1]):
    client.reset(ports=directions)
    client.set_port_attr(ports = directions, promiscuous = False)
    for direction in directions:
        client.add_streams(streams[direction], ports=[direction])

    client.clear_stats()

    print "PPS = ", pps
    if pps:
        mult_factor = "%dkpps"%rate
    else:
        mult_factor = "%d%%"%rate
    client.start(ports=directions, mult=mult_factor, duration=duration)
    
    client.wait_on_traffic(ports=directions)

    stats = client.get_stats()
    #print client.get_xstats(0)
    return stats

def get_total(stats, ports, metric):
    opackets = 0
    for p in ports:
        opackets += stats[p][metric]
    return opackets

def get_opackets(stats, ports):
    return get_total(stats, ports, "opackets")

def get_drops(stats, ports):
    opackets = get_total(stats, ports, "opackets")
    ipackets = get_total(stats, ports, "ipackets")
    drops = opackets - ipackets
    return drops

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

def start_experiment(maxRate, startRate, numIterations, duration, profile, bidir=True, pps=False, vlan=None):
    client = STLClient(server=t_global.args.ip)
    client.connect()

    src = ip_range["src"]
    dst = ip_range["dst"]

    streams = [[], []]
    total_pps = 100

    if bidir:
        directions = [0, 1]
    else:
        directions = [0]

    for direction in directions:
        vm = get_vm(direction)
        for i in range(len(profile)):
            x = profile[i]
            latency_pps = total_pps * x['ratio']
            pkt = create_pkt(x["size"], vm, vlan)
            streams[direction].append(STLStream(packet=pkt, mode=STLTXCont(pps = latency_pps), isg=x['isg']))
       
        lat_stream = STLStream(packet = create_pkt(128, vm, vlan), mode = STLTXCont(pps=1000), 
                                flow_stats = STLFlowLatencyStats(pg_id = (direction+12)))
        streams[direction].append(lat_stream)

    rate = startRate
    minRate = rate
    
    if pps:
        unit = "kpps"
    else:
        unit = "%%"

    converged = False
    for iteration in range(numIterations):
        print "Trying with rate = %d %s . [min, max] = [%d, %s]" % (rate, unit, minRate, str(maxRate))
        success = True
        try:
            stats = single_run(client, streams, rate, duration, pps, directions)
        except Exception as e:
            print str(e)
            success = False
        drops = get_drops(stats, directions)
        opackets = get_opackets(stats, directions)
        print (opackets, drops)
        droprate = drops*1.0/opackets
        
        if success and droprate < 0.0001:   # 0.01%
            # Sounds good
            minRate = rate
        else:
            # LOSS !!!!
            maxRate = rate

        if maxRate == None:
            rate = rate*2
        else:
            rate = int((minRate + maxRate)*1.0/2)

        if rate == minRate:
            converged = True
            break
        time.sleep(5)
 
    print "FINAL RATE = %d %s ; converged = %s" % (rate, unit, str(converged))
    client.disconnect()
 
def process_options ():
    parser = argparse.ArgumentParser(
        usage="""
        Start trex daemon sudo ./t-rex-64 -c 4 -i

        This script is meant to find the traffic load that is able to fully load the DUT. 
        A traffic profile is provided and the script increases the PPS for the traffic profile starting from 

    """,
    description="example for TRex api",
    epilog=" written by harshitg@gatech.edu");

    parser.add_argument("--imix-profile",
                        dest="imix_profile",
                        help='IMIX profile path',
                        type = str
                        )

    parser.add_argument("--ip",
                        dest="ip",
                        help='remote trex ip default local',
                        default="127.0.0.1",
                        type = str
                        )

    parser.add_argument("--max-rate",
                        dest="maxRate",
                        help='Max rate in %% that can be sent to this function (in percentage of link bw or Kpps)',
                        type = int
                        )
    parser.add_argument("--start-rate",
                        dest="startRate",
                        help='Rate to start testing with (in percentage of link bw or Kpps)',
                        default=10,
                        type = int
                        )
    parser.add_argument("--duration",
                        dest="duration",
                        help='Seconds for running single run',
                        default=15,
                        type = int
                        )
    parser.add_argument("--num-iterations",
                        dest="numIterations",
                        help='Max number of iterations',
                        default=15,
                        type = int
                        )
    parser.add_argument("--pps",
                        dest="pps",
                        help='Use PPS as the traffic measurement unit',
                        action='store_true'
                        )
    parser.add_argument("--bidirectional",
                        dest="bidir",
                        help='Generate traffic in both directions',
                        action='store_true'
                        )
    parser.add_argument("--vlan",
                        dest="vlan",
                        help='VLAN ID of network between TRex machine and DUT',
                        type=int
                        )
    t_global.args = parser.parse_args();
    print(t_global.args)

def read_profile(profilePath):
    x = None
    with open(profilePath, "r") as f:
        x = json.load(f)
    f.close()
    return x

def main():
    process_options()
    if t_global.args.pps == False and t_global.args.maxRate == None:
        t_global.args.maxRate = 75

    if t_global.args.imix_profile:
        print "Profile found"
        profile = read_profile(t_global.args.imix_profile)
        if profile:
            start_experiment(t_global.args.maxRate, t_global.args.startRate, t_global.args.numIterations, t_global.args.duration, profile, t_global.args.bidir, t_global.args.pps)
            
    else:
        print "Profile not specified. Using default profile specified in same file above"
        '''
        jsonProfile = json.dumps(imix_table)
        print jsonProfile
        with open("/tmp/imix.profile", "w") as f:
            f.write(jsonProfile)
        f.close()
        with open("/tmp/imix.profile", "r") as f:
            x = json.load(f)
        f.close()
        '''
        start_experiment(t_global.args.maxRate, t_global.args.startRate, t_global.args.numIterations, t_global.args.duration, imix_table, t_global.args.bidir, t_global.args.pps, t_global.args.vlan)

if __name__ == "__main__":
    main()
