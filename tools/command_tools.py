from server import mcp
import subprocess


@mcp.tool()
def run_command(args: list[str]):
    result = subprocess.run(["alpacon", *args], capture_output=True, text=True)
    print(result.stdout)
    return result.stdout, result.stderr
