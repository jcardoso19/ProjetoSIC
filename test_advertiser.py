import asyncio
from common.advertiser import NodeAdvertiser

MY_NODE_NAME = "SIC_NODE_TEST_SERVER"

async def main():
    advertiser = NodeAdvertiser(MY_NODE_NAME)
    
    try:
        await advertiser.run()
    except KeyboardInterrupt:
        advertiser.stop()

if __name__ == "__main__":
    asyncio.run(main())