"""
Search API - Multi-retailer Google Custom Search service.

This FastAPI service performs concurrent searches across UK retailers using Google Custom Search API.
It returns found links which can then be verified by the Link Verification API.

Port: 5001
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
import aiohttp
import asyncio
from typing import List, Dict, Any, Optional
import urllib.parse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# =============================================================================
# FASTAPI APP SETUP
# =============================================================================

app = FastAPI(
    title="Price Pilot Search API",
    description="Multi-retailer Google Custom Search service for price comparison",
    version="1.0.0"
)

# Enable CORS for Chrome extension requests only
# This allows ANY Chrome extension during development,
# later in production we will use a specific extension ID to prevent abuse.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^chrome-extension://[a-z]{32}$",
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

# =============================================================================
# RATE LIMITING
# =============================================================================

# Initialize rate limiter with IP-based limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# Custom exception handler for rate limit exceeded
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"error": "Rate limit exceeded. Please try again later.", "detail": str(exc.detail)}
    )

# =============================================================================
# CONFIGURATION & SECRETS
# =============================================================================

from google.cloud import secretmanager

# Initialize Secret Manager client
_secrets_cache = {}

def get_secret(secret_name: str) -> str:
    """Retrieve a secret from Google Secret Manager."""
    if secret_name in _secrets_cache:
        return _secrets_cache[secret_name]
    
    try:
        project_id = "price-pilot-1765213055260"
        client = secretmanager.SecretManagerServiceClient()
        resource_name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": resource_name})
        secret_value = response.payload.data.decode("UTF-8")
        _secrets_cache[secret_name] = secret_value
        return secret_value
    except Exception as e:
        print(f"Error retrieving secret '{secret_name}': {str(e)}")
        raise

# Fetch credentials from Secret Manager
try:
    GOOGLE_API_KEY = get_secret('GOOGLE_API_KEY')
    GOOGLE_CX = get_secret('GOOGLE_CX')
    print("✅ Secrets loaded from Google Secret Manager")
except Exception as e:
    print(f"❌ Failed to load secrets: {str(e)}")
    raise SystemExit(1)

# Concurrency limit for parallel searches
MAX_CONCURRENT_SEARCHES = 5

# Request timeout in seconds
REQUEST_TIMEOUT = 10

# UK Retailers list
UK_RETAILERS = [
    'amazon.co.uk',
    'argos.co.uk',
    'currys.co.uk',
    'johnlewis.com',
    'asos.com',
    'next.co.uk',
    'boots.com',
    'superdrug.com',
    'tesco.com',
    'sainsburys.co.uk',
    'asda.com',
    'morrisons.com',
    'wickes.co.uk',
    'b-and-q.co.uk',
    'screwfix.com',
    'halfords.com',
    'dunelm.com',
    'ikea.com/gb',
    'selfridges.com',
    'houseoffraser.co.uk',
    'jd.com',
    'footpatrol.com',
    'size.co.uk',
    'catchonline.com',
    'very.co.uk',
    'simply-be.co.uk',
    'scan.co.uk',
    'overclockers.co.uk',
    'ebuyer.com'
]


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class SearchRequest(BaseModel):
    searchQuery: str
    productTitle: Optional[str] = None


class SearchResult(BaseModel):
    retailer: str
    link: str
    title: str
    snippet: str


class SearchQueryStatus(BaseModel):
    retailer: str
    status: str
    error: Optional[str] = None


class SearchResponse(BaseModel):
    success: bool
    results: List[SearchResult] = []
    searchQueries: List[SearchQueryStatus] = []
    totalRetailers: int = 0
    successfulSearches: int = 0
    foundResults: int = 0
    apiError: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    message: str
    port: int
    retailers: int
    maxConcurrency: int


class RetailersResponse(BaseModel):
    retailers: List[str]
    count: int


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_retailer_queries(product_query: str) -> List[Dict[str, str]]:
    """Generate site-specific search queries for each UK retailer."""
    return [
        {
            'retailer': retailer,
            'query': f'site:{retailer} {product_query}'
        }
        for retailer in UK_RETAILERS
    ]


async def test_api_credentials(session: aiohttp.ClientSession) -> Dict[str, Any]:
    """Test Google Custom Search API credentials with a simple query."""
    test_url = f'https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q=test'
    
    try:
        async with session.get(test_url, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as response:
            data = await response.json()
            
            if response.status != 200 or 'error' in data:
                error_msg = data.get('error', {}).get('message', f'HTTP {response.status}')
                return {'success': False, 'error': error_msg}
            
            return {'success': True}
            
    except asyncio.TimeoutError:
        return {'success': False, 'error': 'API request timed out'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


async def search_retailer(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    retailer: str,
    query: str
) -> Dict[str, Any]:
    """Perform a Google Custom Search for a specific retailer."""
    async with semaphore:
        encoded_query = urllib.parse.quote(query)
        url = f'https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={encoded_query}'
        
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as response:
                data = await response.json()
                
                if response.status != 200:
                    error_msg = data.get('error', {}).get('message', f'HTTP {response.status}')
                    return {
                        'retailer': retailer,
                        'status': 'error',
                        'error': error_msg,
                        'result': None
                    }
                
                if 'error' in data:
                    return {
                        'retailer': retailer,
                        'status': 'error',
                        'error': data['error'].get('message', 'Unknown error'),
                        'result': None
                    }
                
                # Check if we got any results
                items = data.get('items', [])
                if not items:
                    return {
                        'retailer': retailer,
                        'status': 'success',
                        'result': None
                    }
                
                # Return the first result
                first_item = items[0]
                return {
                    'retailer': retailer,
                    'status': 'success',
                    'result': {
                        'link': first_item.get('link', ''),
                        'title': first_item.get('title', ''),
                        'snippet': first_item.get('snippet', '')
                    }
                }
                
        except asyncio.TimeoutError:
            return {
                'retailer': retailer,
                'status': 'error',
                'error': 'Request timed out',
                'result': None
            }
        except Exception as e:
            return {
                'retailer': retailer,
                'status': 'error',
                'error': str(e),
                'result': None
            }


async def perform_multi_retailer_search(search_query: str, product_title: str) -> Dict[str, Any]:
    """Perform concurrent searches across all UK retailers."""
    async with aiohttp.ClientSession() as session:
        # Test API credentials first
        api_test = await test_api_credentials(session)
        
        if not api_test['success']:
            print(f"API test failed: {api_test['error']}")
            return {
                'success': False,
                'apiError': api_test['error'],
                'results': [],
                'searchQueries': [{'retailer': 'API_TEST', 'status': 'error', 'error': api_test['error']}],
                'totalRetailers': 0,
                'successfulSearches': 0,
                'foundResults': 0
            }
        
        # Generate queries and search concurrently
        retailer_queries = generate_retailer_queries(search_query)
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)
        
        tasks = [
            search_retailer(session, semaphore, rq['retailer'], rq['query'])
            for rq in retailer_queries
        ]
        
        search_results = await asyncio.gather(*tasks)
        
        # Process results
        results = []
        search_queries = []
        
        for sr in search_results:
            query_status = {'retailer': sr['retailer'], 'status': sr['status']}
            if sr.get('error'):
                query_status['error'] = sr['error']
            search_queries.append(query_status)
            
            if sr['status'] == 'success' and sr['result']:
                results.append({
                    'retailer': sr['retailer'],
                    'link': sr['result']['link'],
                    'title': sr['result']['title'],
                    'snippet': sr['result']['snippet']
                })
        
        successful_searches = sum(1 for sq in search_queries if sq['status'] == 'success')
        print(f"Search complete: {len(results)} results from {successful_searches}/{len(retailer_queries)} retailers")
        
        return {
            'success': True,
            'results': results,
            'searchQueries': search_queries,
            'totalRetailers': len(retailer_queries),
            'successfulSearches': successful_searches,
            'foundResults': len(results)
        }


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.get("/health", response_model=HealthResponse)
@limiter.limit("100/minute")
async def health_check(request: Request):
    """Health check endpoint."""
    return {
        'status': 'ok',
        'message': 'Search API is running',
        'port': 5001,
        'retailers': len(UK_RETAILERS),
        'maxConcurrency': MAX_CONCURRENT_SEARCHES
    }


@app.post("/search", response_model=SearchResponse)
@limiter.limit("20/minute")
async def search(request: Request):
    """
    Perform multi-retailer search for a product.
    
    - **searchQuery**: The product search query
    - **productTitle**: Optional product title for logging (defaults to searchQuery)
    
    Rate limited to 20 requests per minute per IP address.
    """
    # Parse the JSON body manually since slowapi requires 'request' as the first parameter
    try:
        body = await request.json()
        search_request = SearchRequest(**body)
    except ValidationError as e:
        # Return 422 for Pydantic validation errors
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request body: {str(e)}")
    
    search_query = search_request.searchQuery
    product_title = search_request.productTitle or search_query
    
    if not search_query:
        raise HTTPException(status_code=400, detail="Missing required field: searchQuery")
    
    print(f"Search request: {product_title[:60]}")
    
    try:
        result = await perform_multi_retailer_search(search_query, product_title)
        return result
    except Exception as e:
        print(f"Error in search: {str(e)}")
        return {
            'success': False,
            'apiError': f'Internal error: {str(e)}',
            'results': [],
            'searchQueries': [],
            'totalRetailers': 0,
            'successfulSearches': 0,
            'foundResults': 0
        }


@app.get("/retailers", response_model=RetailersResponse)
@limiter.limit("100/minute")
async def get_retailers(request: Request):
    """Get list of supported UK retailers."""
    return {
        'retailers': UK_RETAILERS,
        'count': len(UK_RETAILERS)
    }


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    import uvicorn
    import os
    
    # Get port from environment variable or default to 8080 (required for Cloud Run)
    port = int(os.environ.get('PORT', 8080))
    host = '0.0.0.0' 
    uvicorn.run(app, host=host, port=port)
