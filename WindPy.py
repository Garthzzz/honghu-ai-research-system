import urllib.request
import urllib.parse
import json
import os
import pandas as pd
from io import StringIO

# 定义服务器地址
SERVER_URL = [
    'http://10.5.5.230:8080',
    'http://10.5.1.230:8080',
]   

from collections import namedtuple
class wdata(namedtuple('wdataBase', ['ErrorCode', 'dfData', 'Times', 'Data'])):
    ...
class WMeta(type):
    _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    _timeout = float(os.getenv("WIND_HTTP_TIMEOUT_SECONDS", "30"))
    _last_error = ""
    _connected = False

    def send_get_request(cls,method,*args,**kwargs):
        for i, server_url in enumerate(SERVER_URL):
            try:
                # 构造请求（可添加查询参数）
                params = {'method': method, 'args': args, 'kwargs': kwargs}
                query_string = urllib.parse.urlencode(params)
                full_url = f"{server_url}?{query_string}"
                
                # 发送GET请求
                # 两个固定地址都是公司内网 HTTP 服务。显式禁用系统代理，避免
                # 本机 VPN 的 HTTP_PROXY/HTTPS_PROXY 把 RFC1918 请求转发成 502。
                with cls._opener.open(full_url, timeout=cls._timeout) as response:
                    # 读取响应数据
                    response_body = response.read()
                    # 解析响应JSON
                    df = pd.read_json(StringIO(response_body.decode('utf-8')),convert_dates=['tradedate'])
                    
                #print("=== GET请求响应结果 ===")
                #print(f"响应状态码：{response.getcode()}")
                #print(f"响应数据：{df}")
                
                errorCode = response.getcode()
                if errorCode == 200: errorCode = 0
                if errorCode == 0:
                    cls._connected = True
                    cls._last_error = ""
                    return wdata(errorCode,df,df.index.tolist(),df.T.values.tolist())
                else:
                    cls._last_error = f"{server_url} 返回 HTTP {errorCode}"
                    if i == len(SERVER_URL) - 1:
                        cls._connected = False
                        return wdata(errorCode,df,df.index.tolist(),df.T.values.tolist())
            except Exception as e:
                cls._last_error = f"{server_url}: {type(e).__name__}: {str(e)[:240]}"
                if i == len(SERVER_URL) - 1:
                    cls._connected = False
                    return wdata(-1, pd.DataFrame(), [], [])
    def __getattr__(cls, method_name):
        def dynamic_method(*args, **kwargs):
            kwargs["usedf"]=True
            return cls.send_get_request(method_name,*args,**kwargs)
        return dynamic_method
class w(metaclass=WMeta):
    def start():
        return wdata(0, pd.DataFrame(), [], [])
    def stop():
        w._connected = False
        return wdata(0, pd.DataFrame(), [], [])
    def isconnected():
        return bool(getattr(w, "_connected", False))
