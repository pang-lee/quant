# 使用官方的 Miniconda 基礎映像
FROM continuumio/miniconda3

LABEL Name="Shih-Pang"
LABEL Version="1.0.0"

# 設定工作目錄
WORKDIR /app

# 複製 environment.yml 檔案到容器中
COPY ../environment.yml /app/

# 創建新的 conda 環境，並安裝必要的 Python 套件
RUN conda env create -f /app/environment.yml -p /opt/myenv

# 將 /opt/myenv/bin 加入 PATH
ENV PATH /opt/myenv/bin:$PATH

# 複製應用程式程式碼（此時 /app 目錄內容會被本機掛載覆蓋，但 /opt/myenv 不會受影響）
COPY ../app /app

# 暴露應用程式運行的端口號（例如 5000）
EXPOSE 5000

# 定義容器啟動時執行的命令
CMD ["python", "index.py"]