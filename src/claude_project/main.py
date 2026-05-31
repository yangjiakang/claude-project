"""Claude Project —— API 使用分析工具 & 网页资源爬取器"""
# 项目主入口模块，负责启动 CLI 命令行界面

from claude_project.cli import main  # 从 CLI 模块导入 main 函数作为程序入口

if __name__ == "__main__":  # 当脚本直接运行时（而非被导入时）
    main()  # 调用 CLI 主函数，启动整个命令行工具
