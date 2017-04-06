#!/usr/bin/python

import allow2, sys, getopt

def usage():
   print 'pair.py -u <username> -p <password> <deviceToken> <deviceName>'
   sys.exit(2)

def main(argv):
   inputfile = ''
   outputfile = ''
   usr = None
   pwd = None
   try:
      opts, args = getopt.getopt(argv,"hu:p:",["ifile=","ofile="])
   except getopt.GetoptError:
      usage()
   for opt, arg in opts:
      if opt == '-h':
         usage()
      elif opt in ("-u", "--username"):
         usr = arg
      elif opt in ("-p", "--password"):
         pwd = arg
   if (len(args) != 2) or (usr is None) or (pwd is None):
      usage()

   userId, pairId, children = allow2.pair(usr, pwd, args[0], args[1])

   print 'userId: ', userId
   print 'pairId: ', pairId
   print 'children: ', children

if __name__ == "__main__":
   main(sys.argv[1:])
