#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
屏幕截图工具 - 支持全屏、区域截图、Base64 输出
依赖: pip install mss Pillow
"""

import os
import sys
import argparse
import base64
from datetime import datetime
from pathlib import Path

import mss
import mss.tools


def screenshot_full(save_path: str = None) -> str:
    """
    全屏截图并保存
    
    Args:
        save_path: 保存路径，默认保存到 data/1111/
    
    Returns:
        保存的文件路径
    """
    if save_path is None:
        save_dir = Path("data/1111")
        save_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = save_dir / f"screenshot_{timestamp}.png"
    
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # 主屏幕
        sct.shot(mon=monitor, output=str(save_path))
    
    return str(save_path)


def screenshot_region(left: int, top: int, width: int, height: int, 
                       save_path: str = None) -> str:
    """
    截取指定区域
    
    Args:
        left: 左上角 X 坐标
        top: 左上角 Y 坐标
        width: 宽度
        height: 高度
        save_path: 保存路径
    
    Returns:
        保存的文件路径
    """
    if save_path is None:
        save_dir = Path("data/1111")
        save_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = save_dir / f"screenshot_region_{timestamp}.png"
    
    with mss.mss() as sct:
        monitor = {
            "left": left,
            "top": top,
            "width": width,
            "height": height
        }
        sct.shot(mon=monitor, output=str(save_path))
    
    return str(save_path)


def screenshot_base64() -> str:
    """
    获取全屏截图的 Base64 编码
    
    Returns:
        Base64 编码的 PNG 图片
    """
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        screenshot = sct.grab(monitor)
        
    # 转换为 PNG 并 Base64 编码
    png_data = mss.tools.to_png(screenshot.rgb, screenshot.size)
    return base64.b64encode(png_data).decode('utf-8')


def get_monitors() -> list:
    """
    获取所有显示器信息
    
    Returns:
        显示器列表
    """
    with mss.mss() as sct:
        monitors = []
        for i, m in enumerate(sct.monitors):
            monitors.append({
                "index": i,
                "left": m["left"],
                "top": m["top"],
                "width": m["width"],
                "height": m["height"]
            })
    return monitors


def main():
    parser = argparse.ArgumentParser(description='屏幕截图工具')
    parser.add_argument('--full', action='store_true', help='全屏截图')
    parser.add_argument('--region', nargs=4, type=int, 
                        metavar=('LEFT', 'TOP', 'WIDTH', 'HEIGHT'),
                        help='区域截图: 左 上 宽 高')
    parser.add_argument('--base64', action='store_true', help='输出 Base64')
    parser.add_argument('--save', type=str, help='保存路径')
    parser.add_argument('--info', action='store_true', help='显示显示器信息')
    
    args = parser.parse_args()
    
    if args.info:
        print("显示器信息:")
        for m in get_monitors():
            print(f"  [{m['index']}] {m['width']}x{m['height']} at ({m['left']}, {m['top']})")
        return
    
    if args.base64:
        print(screenshot_base64())
        return
    
    if args.region:
        left, top, width, height = args.region
        path = screenshot_region(left, top, width, height, args.save)
    else:
        path = screenshot_full(args.save)
    
    print(f"截图已保存: {path}")


if __name__ == '__main__':
    main()
