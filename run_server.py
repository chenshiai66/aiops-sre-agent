"""开发用启动脚本 —— 让 PyCharm 可以直接右键运行。

⚠️ 必须从这里启动，不要直接跑 app/main.py：
   直接跑 app 下的文件会把 app/ 放进 sys.path[0]，
   于是 app 里的任何包名都会遮蔽同名的第三方库。
   （已经踩过一次：app/mcp/ 遮蔽了 mcp 库，
     而报错信息指向我们自己的文件，非常难查。）

命令行等价于：
    uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)