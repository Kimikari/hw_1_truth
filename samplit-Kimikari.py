#!/usr/bin/env python
import random, sys

def main():
    filename = sys.argv[1]
    with open(filename, encoding="utf-8") as f:
        for line in f:
            if(random.random()<0.01):
                print(line, end='')


if __name__ == '__main__':
    main()