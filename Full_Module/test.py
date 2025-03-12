str1 = """{"evaluation":"insufficient_information",\n                        "explanation":"CANNOT FIND ANY RELEVANT DOCUMENT"}"""

import json
json1 = json.loads(str1) if type(str1)==str else str1

print("json1", json1)
print(type(json1))