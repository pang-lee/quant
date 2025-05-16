#!/bin/bash

# 刪除 log/ 目錄及其內容
if [ -d "log" ]; then
    rm -rf log/
    echo "已刪除 log/ 目錄"
else
    echo "log/ 目錄不存在"
fi

# 刪除 shioaji.log 檔案
if [ -f "shioaji.log" ]; then
    rm shioaji.log
    echo "已刪除 shioaji.log 檔案"
else
    echo "shioaji.log 檔案不存在"
fi