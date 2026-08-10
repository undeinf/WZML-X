import re
import time
from urllib.parse import urlparse
from niquests import AsyncSession
from bot import LOGGER

class Rapidgator:
    _instances = {}

    def __new__(cls, username, password):
        key = (username, password)
        if key not in cls._instances:
            instance = super().__new__(cls)
            instance.username = username
            instance.password = password
            instance.session_id = None
            instance.last_check = 0
            instance.session = AsyncSession()
            cls._instances[key] = instance
        return cls._instances[key]

    async def login(self):
        if self.session_id and time.time() - self.last_check < 3000:
            return self.session_id

        login_url = "https://rapidgator.net/api/user/login"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        login_data = {
            'username': self.username,
            'password': self.password
        }
        try:
            response = await self.session.post(login_url, data=login_data, headers=headers)
            if response.status_code != 200:
                raise Exception(f"HTTP login status {response.status_code}")
            
            result = response.json()
            resp = result.get('response') or {}
            
            if resp.get('state') in ('two_factor_auth_required', 'twofactorauthrequired'):
                raise Exception("Login failed: 2FA is enabled. Please disable it on Rapidgator.")
            
            session_id = resp.get('session_id') or resp.get('token')
            if not session_id:
                error_msg = resp.get('msg', 'Unknown error')
                raise Exception(f"Login failed: {error_msg}")
            
            self.session_id = session_id
            self.last_check = time.time()
            return self.session_id
        except Exception as e:
            LOGGER.error(f"Rapidgator login error for user {self.username}: {str(e)}")
            raise e

    async def get_account_info(self):
        try:
            await self.login()
            return "⌬ <b>Rapidgator Account Info</b>\n│\n┖ Status: ✓ Active Session"
        except Exception as e:
            return f"⌬ <b>Rapidgator Account Info</b>\n│\n┖ Error: {str(e)}"

    async def get_download_link(self, url: str):
        session_id = await self.login()
        
        file_id_match = re.search(r'(?:rapidgator\.(?:net|asia)|rg\.to)/file/([a-zA-Z0-9]+)', url)
        if not file_id_match:
            raise Exception("Invalid Rapidgator URL format")
            
        file_id = file_id_match.group(1)
        clean_url = url.split('?')[0].replace('.html', '')
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://rapidgator.net/'
        }

        # 1. Fetch file info (filename and size) using Rapidgator API first
        # This prevents running a HEAD request on the direct link which could expire/lock it.
        filename = None
        total_size = 0
        try:
            info_url = f"https://rapidgator.net/api/file/info?sid={session_id}&url={clean_url}"
            info_response = await self.session.get(info_url, headers=headers)
            if info_response.status_code == 200:
                info_result = info_response.json()
                if info_result.get('response_status') == 200:
                    info_data = info_result.get('response', {})
                    filename = info_data.get('filename')
                    total_size = int(info_data.get('size', 0))
        except Exception as e:
            LOGGER.warning(f"Failed to fetch file info from API: {e}")

        # Fallbacks for filename if info API failed or didn't return it
        if not filename:
            try:
                clean_input_url = url.split('?')[0].split('#')[0]
                path_segments = [seg for seg in urlparse(clean_input_url).path.split('/') if seg]
                if len(path_segments) >= 3 and path_segments[0] == 'file':
                    name_seg = path_segments[2]
                    if name_seg.lower().endswith('.html'):
                        name_seg = name_seg[:-5]
                    filename = name_seg
                elif path_segments and '.' in path_segments[-1] and path_segments[-1] != 'file':
                    name_seg = path_segments[-1]
                    if name_seg.lower().endswith('.html'):
                        name_seg = name_seg[:-5]
                    filename = name_seg
            except Exception as e:
                LOGGER.warning(f"Failed to extract filename from input URL: {e}")

        if not filename:
            filename = f'rapidgator_{file_id}'
            
        filename = re.sub(r'[\\/*?:"<>|]', '', filename)
        
        # 2. Get premium download URL from Rapidgator API
        api_download_url = f"https://rapidgator.net/api/file/download?sid={session_id}&url={clean_url}"
        
        api_response = await self.session.get(api_download_url, headers=headers)
        if api_response.status_code != 200:
            if api_response.status_code == 401:
                self.session_id = None
                session_id = await self.login()
                api_download_url = f"https://rapidgator.net/api/file/download?sid={session_id}&url={clean_url}"
                api_response = await self.session.get(api_download_url, headers=headers)
                if api_response.status_code != 200:
                    raise Exception(f"API returned status {api_response.status_code} after session refresh")
            else:
                raise Exception(f"API returned status {api_response.status_code}")
                
        result = api_response.json()
        response_status = result.get('response_status', 0)
        if response_status != 200:
            error_msg = result.get('response_details', 'Unknown error')
            if 'session' in error_msg.lower() or 'login' in error_msg.lower():
                self.session_id = None
            raise Exception(f"Rapidgator API error: {error_msg}")
            
        response_data = result.get('response', {})
        download_url = response_data.get('url')
        if not download_url:
            raise Exception("No download URL in API response")
            
        return download_url, filename, total_size

async def get_rapidgator_account_info(username, password):
    rg = Rapidgator(username, password)
    return await rg.get_account_info()

async def check_rapidgator_connection():
    from bot.core.config_manager import Config
    if not Config.RAPIDGATOR_EMAIL or not Config.RAPIDGATOR_PASSWORD:
        return
    LOGGER.info("Rapidgator: Testing global premium credentials...")
    try:
        rg = Rapidgator(Config.RAPIDGATOR_EMAIL, Config.RAPIDGATOR_PASSWORD)
        await rg.login()
        LOGGER.info("Rapidgator: Global premium account connected successfully!")
    except Exception as e:
        LOGGER.error(f"Rapidgator: Global premium account connection failed: {e}")

async def get_rapidgator_link(url: str, username, password):
    rg = Rapidgator(username, password)
    return await rg.get_download_link(url)
