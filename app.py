from fastapi import FastAPI, Request


import uvicorn


app = FastAPI()


prefix_python_codes = """
# 导入 SymPy 库的常用组件
from sympy import symbols, Eq, solve, simplify, diff, integrate, sin, cos, exp, sqrt
import numpy as np
# 定义一些符号变量
x, y, z = symbols('x y z')

"""


from code_interpreter import CodeInterpreter

code_interpreter = CodeInterpreter()
code_interpreter.call("print('代码解释器启动成功！！')")


@app.post("/python")
async def python(request: Request):
    json_data = await request.json()
    print(json_data)
    code_str = json_data["input"]
    code_str = prefix_python_codes + code_str
    result = code_interpreter.call(code_str)
    print(f"result is {result},type is {type(result)}")
    return result

    # return {"result": result}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8826)
