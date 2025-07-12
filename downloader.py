#!/usr/bin/env python3
"""
Multi-threaded nginx directory downloader
Downloads all files from nginx directory listings recursively
"""

import os
import sys
import time
import argparse
from pathlib import Path
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Set

import requests
from bs4 import BeautifulSoup


class NginxDirectoryDownloader:
    def __init__(self, base_url: str, output_dir: str = "downloads", max_workers: int = 8, max_retries: int = 5):
        self.base_url = base_url.rstrip('/')
        self.output_dir = Path(output_dir)
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.session = requests.Session()
        self.downloaded_files = set()
        self.failed_downloads = []
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def parse_directory_listing(self, url: str) -> tuple[List[str], List[str]]:
        """Parse nginx directory listing and return files and subdirectories"""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            links = soup.find_all('a')
            
            files = []
            directories = []
            
            for link in links:
                href = link.get('href')
                if not href or href.startswith(('http://', 'https://', '../', '?')):
                    continue
                
                if href.endswith('/'):
                    # It's a directory
                    directories.append(href.rstrip('/'))
                else:
                    # It's a file
                    files.append(href)
            
            return files, directories
            
        except Exception as e:
            print(f"Error parsing directory {url}: {e}")
            return [], []
    
    def download_file(self, file_url: str, local_path: Path) -> bool:
        """Download a single file with resume support and retry mechanism"""
        for attempt in range(self.max_retries):
            try:
                # Create parent directories if they don't exist
                local_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Check if file exists and get its size
                existing_size = 0
                if local_path.exists():
                    existing_size = local_path.stat().st_size
                    
                    # Get remote file size to check if download is complete
                    try:
                        head_response = self.session.head(file_url, timeout=10)
                        remote_size = int(head_response.headers.get('content-length', 0))
                        
                        if existing_size == remote_size and remote_size > 0:
                            print(f"✓ Skipped (complete): {local_path}")
                            return True
                        elif existing_size > 0:
                            print(f"⟳ Resuming: {local_path} (from {existing_size} bytes)")
                    except:
                        # If HEAD request fails, check if server supports range requests
                        pass
                
                # Set up headers for resume if partial file exists
                headers = {}
                if existing_size > 0:
                    headers['Range'] = f'bytes={existing_size}-'
                
                response = self.session.get(file_url, headers=headers, timeout=30, stream=True)
                
                # Handle partial content (206) or full content (200)
                if response.status_code == 206:
                    # Resuming download
                    mode = 'ab'
                elif response.status_code == 200:
                    # Full download (server doesn't support resume or file is new)
                    mode = 'wb'
                    existing_size = 0
                else:
                    response.raise_for_status()
                    mode = 'wb'
                
                with open(local_path, mode) as f:
                    downloaded = existing_size
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                
                if existing_size > 0:
                    print(f"✓ Resumed: {local_path}")
                else:
                    print(f"✓ Downloaded: {local_path}")
                return True
                
            except Exception as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                    print(f"⚠ Attempt {attempt + 1}/{self.max_retries} failed for {local_path}: {e}")
                    print(f"  Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    print(f"✗ Failed to download {file_url} after {self.max_retries} attempts: {e}")
                    self.failed_downloads.append(file_url)
                    return False
        
        return False
    
    def get_all_files_recursive(self, url: str, relative_path: str = "") -> List[tuple[str, str]]:
        """Recursively get all files from directory and subdirectories"""
        files_to_download = []
        
        print(f"Scanning: {url}")
        files, directories = self.parse_directory_listing(url)
        
        # Add files in current directory
        for file in files:
            file_url = urljoin(url + '/', file)
            local_file_path = os.path.join(relative_path, file)
            files_to_download.append((file_url, local_file_path))
        
        # Recursively scan subdirectories
        for directory in directories:
            subdir_url = urljoin(url + '/', directory + '/')
            subdir_relative_path = os.path.join(relative_path, directory)
            subdir_files = self.get_all_files_recursive(subdir_url, subdir_relative_path)
            files_to_download.extend(subdir_files)
        
        return files_to_download
    
    def download_all(self, target_folder: str = ""):
        """Download all files from the target folder recursively"""
        start_url = urljoin(self.base_url + '/', target_folder)
        if target_folder and not start_url.endswith('/'):
            start_url += '/'
        
        print(f"Starting download from: {start_url}")
        print(f"Output directory: {self.output_dir.absolute()}")
        print(f"Max workers: {self.max_workers}")
        print("-" * 50)
        
        # Get all files recursively
        files_to_download = self.get_all_files_recursive(start_url, target_folder)
        
        if not files_to_download:
            print("No files found to download.")
            return
        
        print(f"\nFound {len(files_to_download)} files to download")
        print("-" * 50)
        
        # Download files using thread pool
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_file = {}
            
            for file_url, local_file_path in files_to_download:
                local_path = self.output_dir / local_file_path
                future = executor.submit(self.download_file, file_url, local_path)
                future_to_file[future] = (file_url, local_path)
            
            # Process completed downloads
            completed = 0
            for future in as_completed(future_to_file):
                completed += 1
                file_url, local_path = future_to_file[future]
                
                try:
                    success = future.result()
                    if success:
                        self.downloaded_files.add(str(local_path))
                except Exception as e:
                    print(f"✗ Error downloading {file_url}: {e}")
                    self.failed_downloads.append(file_url)
                
                # Progress indicator
                print(f"Progress: {completed}/{len(files_to_download)} files")
        
        # Summary
        elapsed_time = time.time() - start_time
        print("\n" + "=" * 50)
        print(f"Download completed in {elapsed_time:.2f} seconds")
        print(f"Successfully downloaded: {len(self.downloaded_files)} files")
        print(f"Failed downloads: {len(self.failed_downloads)} files")
        
        if self.failed_downloads:
            print("\nFailed downloads:")
            for failed_url in self.failed_downloads:
                print(f"  - {failed_url}")


def main():
    parser = argparse.ArgumentParser(description="Download files from nginx directory listing")
    parser.add_argument("url", help="Base URL of the nginx server")
    parser.add_argument("-f", "--folder", default="", help="Target folder to download (relative to base URL)")
    parser.add_argument("-o", "--output", default="downloads", help="Output directory (default: downloads)")
    parser.add_argument("-t", "--threads", type=int, default=8, help="Number of download threads (default: 8)")
    parser.add_argument("-r", "--retries", type=int, default=5, help="Maximum retry attempts per file (default: 5)")
    
    args = parser.parse_args()
    
    # Validate URL
    parsed_url = urlparse(args.url)
    if not parsed_url.scheme or not parsed_url.netloc:
        print("Error: Invalid URL provided")
        sys.exit(1)
    
    try:
        downloader = NginxDirectoryDownloader(
            base_url=args.url,
            output_dir=args.output,
            max_workers=args.threads,
            max_retries=args.retries
        )
        
        downloader.download_all(args.folder)
        
    except KeyboardInterrupt:
        print("\nDownload interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()