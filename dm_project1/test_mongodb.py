from pymongo import MongoClient

# 连接本地 MongoDB
client = MongoClient(
    "mongodb://127.0.0.1:27017/",
    serverSelectionTimeoutMS=5000
)

try:
    # 测试连接
    client.admin.command("ping")
    print("MongoDB 连接成功！")

    # 选择本次大作业数据库
    db = client["dm_project1"]

    print("当前数据库：", db.name)

except Exception as e:
    print("MongoDB 连接失败：", e)

finally:
    client.close()