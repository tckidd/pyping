#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Usage:
  pyping.py ( <host> | -f <FILENAME>) [--ip] [-s <seconds>][-n <count>] [-o <timeout>]
  pyping.py -h | --help | --version

Options:
    -n <count>  ping测的次数，默认为4次 [default: 4]
    -s <seconds>    设置每次ping测之间的间隔时间,默认为1秒 [default: 1]
    -o <timeout>    设置响应超时时间，默认为2秒[default: 2]
    -f <FILENAME>       输入文件名读取文件中的host列表
    --ip    调用ipip.net的借口查询IP地址所在城市
"""
import sys
reload(sys)
sys.setdefaultencoding("utf-8")


import os, sys, socket, struct, select, time
import threading
import httplib2, urllib
from docopt import docopt
from os.path import exists
import csv


#print sys.getdefaultencoding()

if sys.platform == "win32":
    # On Windows, the best timer is time.clock()
    default_timer = time.clock
else:
    # On most other platforms the best timer is time.time()
    default_timer = time.time

# From /usr/include/linux/icmp.h; your milage may vary.
ICMP_ECHO_REQUEST = 8 # Seems to be the same on Solaris.


def checksum(source_string):
    """
    I'm not too confident that this is right but testing seems
    to suggest that it gives the same answers as in_cksum in ping.c
    """
    sum = 0
    countTo = (len(source_string)/2)*2
    count = 0
    while count<countTo:
        thisVal = ord(source_string[count + 1])*256 + ord(source_string[count])
        sum = sum + thisVal
       # sum = sum & 0xffffffff # Necessary?
        count = count + 2

    if countTo<len(source_string):
        sum = sum + ord(source_string[len(source_string) - 1])
       # sum = sum & 0xffffffff # Necessary?

    sum = (sum >> 16)  +  (sum & 0xffff)
    sum = sum + (sum >> 16)
    answer = ~sum
    # ~ 按位取反
    answer = answer & 0xffff

    # Swap bytes. Bugger me if I know why.
    answer = answer >> 8 | (answer << 8 & 0xff00)

    return answer


def receive_one_ping(my_socket, ID, timeout):
    """
    receive the ping from the socket.
    """
    timeLeft = timeout
    while True:
        startedSelect = default_timer()
        whatReady = select.select([my_socket], [], [], timeLeft)
        howLongInSelect = (default_timer() - startedSelect)
        if whatReady[0] == []: # Timeout
            return

        timeReceived = default_timer()
        recPacket, addr = my_socket.recvfrom(1024)
        icmpHeader = recPacket[20:28]
        type, code, checksum, packetID, sequence = struct.unpack(
            "bbHHh", icmpHeader
        )
        # Filters out the echo request itself.
        # This can be tested by pinging 127.0.0.1
        # You'll see your own request
        if type != 8 and packetID == ID:
            bytesInDouble = struct.calcsize("d")
            timeSent = struct.unpack("d", recPacket[28:28 + bytesInDouble])[0]
            return timeReceived - timeSent

        timeLeft = timeLeft - howLongInSelect
        if timeLeft <= 0:
            return


def send_one_ping(my_socket, dest_addr, ID, seq):
    """
    Send one ping to the given >dest_addr<.
    """
    #dest_addr  =  socket.gethostbyname(dest_addr)

    # Header is type (8), code (8), checksum (16), id (16), sequence (16)
    my_checksum = 0

    # Make a dummy heder with a 0 checksum.
    header = struct.pack("bbHHh", ICMP_ECHO_REQUEST, 0, my_checksum, ID, seq)
    # bbHHh是fmt的类型，b signed char 1 byte, H unsigned short 2 byte, h short 2 byte。详见 struct 7.3.2.2 Format Characters


    bytesInDouble = struct.calcsize("d")
    data = (192 - bytesInDouble) * "Q"
    data = struct.pack("d", default_timer()) + data

    # Calculate the checksum on the data and the dummy header.
    my_checksum = checksum(header + data)

    # Now that we have the right checksum, we put that in. It's just easier
    # to make up a new header than to stuff it into the dummy.
    header = struct.pack(
        "bbHHh", ICMP_ECHO_REQUEST, 0, socket.htons(my_checksum), ID, seq
    )
    packet = header + data
    my_socket.sendto(packet, (dest_addr, 1)) # address must be a 2-tuple (host,port)


def do_one(dest_addr, seq, timeout=4):
    """
    Returns either the delay (in seconds) or none on timeout.
    timeout default is same as Windows Cmd
    """
    icmp_protocol = socket.getprotobyname("icmp")
    my_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, icmp_protocol)
    my_ID = threading.current_thread().ident & 0xFFFF
    send_one_ping(my_socket, dest_addr, my_ID, seq)
    delay = receive_one_ping(my_socket, my_ID, timeout)

    my_socket.close()
    return delay




def verbose_ping(dest_addr, timeout = 2, count = 4, sleep = 1):
    """
    Send >count< ping to >dest_addr< with the given >timeout< and display
    the result.
    """
    success_count = 0
    total_delay= 0
    for i in xrange(count):
        localtime = time.asctime(time.localtime(time.time()))
        print "%s ping %s..." % (localtime,dest_addr),
        try:
            delay  =  do_one(dest_addr, i+1, timeout)
        except socket.gaierror, e:
            print "failed. (socket error: '%s')" % e[1]
            break

        if delay  ==  None:
            print "failed. (timeout within %ssec.)" % timeout
        else:
            timetosleep= sleep - delay
            delay  =  delay * 1000
            print "get echo reply in %0.4fms" % delay
            time.sleep(timetosleep)

            success_count = success_count + 1
            total_delay = total_delay + delay
    print "success %s/%s, " % (success_count, count),

    if total_delay >0 :
        average_delay = total_delay/success_count
        print "average delay %0.4fms" % average_delay

    return success_count, count, round(average_delay,2)


if __name__ == '__main__':
    arguments = docopt(__doc__)
    print(arguments)
    count = int(arguments['-n'])
    sleep = int(arguments['-s'])
    timeout = int(arguments['-o'])
    filename = arguments['-f']

    if (arguments['<host>'] != None):
        des_ip = socket.gethostbyname(sys.argv[1])
        if arguments['--ip']:
            url = 'http://freeapi.ipip.net/' + des_ip
            http = httplib2.Http()
            response, content = http.request(url, 'GET')
            print content
        verbose_ping(des_ip, timeout, count, sleep)

    elif (filename!= ""):
        if (exists(filename)):
            txt = open(filename, 'r')
            done = 0
            with open('./data.csv', 'wb') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['host', 'ip', 'sucesscount', 'totalcount', 'average delay'])
                while not done:
                    des_host = txt.readline().strip('\n')
                    #strip替换字符串中的换行符
                    if (des_host != ""):
                        des_ip = socket.gethostbyname(des_host)
                        if arguments['--ip']:
                            url = 'http://freeapi.ipip.net/' + des_ip
                            http = httplib2.Http()
                            response, content = http.request(url, 'GET')
                            print content
                        ping_result = verbose_ping(des_ip, timeout, count, sleep)
                        data = (des_host, des_ip) + ping_result
                        # return 多个值返回结果为tuple，可通过 + 直接进行运算
                        writer.writerow(data)
                    else:
                        done = 1

                csvfile.close()

        else:
            print "no such file"

    else:
        print "no destination host input"
