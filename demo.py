import requests


def send_python_code(python_code):
    result = requests.post(
        "http://localhost:8826/python", json={"input": python_code}
    ).json()
    return result


python_code = """
import numpy as np
print("Hello World")
a = np.array([1,2,3])
print("我还能捕获非print的内容")
a
"""

result = send_python_code(python_code)
print(result)
