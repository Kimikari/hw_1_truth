#!/usr/bin/env python
import random, sys

def main():
    filename = sys.argv[1]
    with open(filename, encoding="utf-8") as f:
        for row in f:
            if(random.random()<0.01):
                print(row, end='')



if __name__ == '__main__':
    main()