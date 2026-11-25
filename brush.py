#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""readoor-brush 启动入口。

    python brush.py --help
"""
import os
import sys

# 允许直接从源码目录运行（不安装）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from readoor.cli import main

if __name__ == "__main__":
    sys.exit(main())
