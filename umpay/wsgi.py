#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WSGI入口文件 - 专门为Vercel部署设计
"""

from app import app

# Vercel需要的应用实例
application = app

if __name__ == "__main__":
    application.run()