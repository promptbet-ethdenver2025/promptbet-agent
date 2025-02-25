import os
import time
import requests
import asyncio
from dotenv import load_dotenv
from datetime import timezone, datetime
from api.twitterapi.tweets import Tweet
from betting_pool_core import call_langgraph_agent
from betting_pool_generator import betting_pool_idea_generator_agent
from db.redis import get_redis_client

# Load environment variables
load_dotenv()

# ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
# ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
# REFRESH_TOKEN = os.getenv("TWITTER_REFRESH_TOKEN")
# CLIENT_ID = os.getenv("TWITTER_CLIENT_ID")
# CLIENT_SECRET = os.getenv("TWITTER_CLIENT_SECRET")

TWITTERAPI_BASE_URL = "https://api.twitterapi.io/twitter"
TWITTERAPI_API_KEY = os.getenv("TWITTERAPI_API_KEY")
LISTENER_TWITTER_HANDLE = os.getenv("LISTENER_TWITTER_HANDLE")
POLLING_INTERVAL = int(os.getenv("POLLING_INTERVAL", 30))
POLLING_WINDOW = int(os.getenv("POLLING_WINDOW", 3600))

# After loading environment variables, add validation
if not all([TWITTERAPI_API_KEY, LISTENER_TWITTER_HANDLE]):
    raise ValueError(
        "Missing required environment variables. Please ensure TWITTERAPI_API_KEY, LISTENER_TWITTER_HANDLE, "
        "are set in your .env file"
    )




def pull_tweets(handle):
    review_timestamp = int(datetime.now(timezone.utc).timestamp() - POLLING_WINDOW)

    print("reviewing since", review_timestamp)
    url = f"{TWITTERAPI_BASE_URL}/user/mentions?userName={handle}&sinceTime={review_timestamp}"
    
    try:
        response = requests.get(url, headers={"x-api-key": TWITTERAPI_API_KEY})
        response.raise_for_status()
        
        data = response.json()
        if data and data["tweets"]:
            return [Tweet.from_dict(tweet) for tweet in data["tweets"]]
        return []
        
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        if response.status_code == 429:
            print("Rate limit exceeded. Consider implementing backoff.")
        elif response.status_code == 401:
            print("Authentication error. Check your API key.")
        elif response.status_code == 404:
            print(f"User {handle} not found.")
        return None
        
    except requests.exceptions.RequestException as err:
        print(f"Error occurred while making request: {err}")
        return None
        
    except ValueError as err:  # Includes JSONDecodeError
        print(f"Error parsing JSON response: {err}")
        return None


async def poll_tweet_mentions():
    redis_client = get_redis_client()
    reviewed_tweets = redis_client.smembers("reviewed_tweets")
    tweets = pull_tweets(LISTENER_TWITTER_HANDLE)
    if tweets is None:
        print("Failed to fetch tweets, will retry in next polling interval")
        return
    if tweets == []:
        print("No tweets found, will retry in next polling interval")
        return
    bets = [propose_bet(tweet_data) for tweet_data in tweets if tweet_data.tweet_id not in reviewed_tweets]
    return asyncio.gather(*bets)


async def propose_bet(tweet_data: Tweet):
    redis_client = get_redis_client()
    print(f"Proposing bet for new tweet from @{tweet_data.author.user_name}: {tweet_data.text}")
    try:
        # Call the Langraph agent
        langgraph_agent_response = await call_langgraph_agent(betting_pool_idea_generator_agent, tweet_data.text, "")
        redis_client.sadd("reviewed_tweets", tweet_data.tweet_id)
        print(f"langgraph_agent_response: {langgraph_agent_response}")
        return langgraph_agent_response
    except Exception as e:
        print("Something went wrong with the bet proposal: ", str(e))

if __name__ == "__main__":
    while True:
        redis_client = get_redis_client()
        asyncio.run(poll_tweet_mentions())
        # print("Waiting 1 hour before next tweet...")
        time.sleep(POLLING_INTERVAL)  
