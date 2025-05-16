#!/bin/bash

# 刪除 log/ 目錄及其內容
if [ -d "log" ]; then
    sudo rm -rf log/
    if [ $? -eq 0 ]; then
        echo "已成功刪除 log/ 目錄"
    else
        echo "刪除 log/ 目錄失敗，可能權限不足或檔案被鎖定"
        exit 1
    fi
else
    echo "log/ 目錄不存在"
fi

# 刪除 shioaji.log 檔案
if [ -f "shioaji.log" ]; then
    sudo rm -f shioaji.log
    if [ $? -eq 0 ]; then
        echo "已成功刪除 shioaji.log 檔案"
    else
        echo "刪除 shioaji.log 檔案失敗，可能權限不足或檔案被鎖定"
        exit 1
    fi
else
    echo "shioaji.log 檔案不存在"
fi