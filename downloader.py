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
from urllib.parse import urljoin, urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Set

import requests
from bs4 import BeautifulSoup


class NginxDirectoryDownloader:
    def __init__(self, base_url: str, output_dir: str = "downloads", max_workers: int = 8, max_retries: int = 5, chunked_download: bool = False, chunk_size_mb: int = 10):
        self.base_url = base_url.rstrip('/')
        self.output_dir = Path(output_dir)
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.chunked_download = chunked_download
        self.chunk_size_mb = chunk_size_mb
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
    
    def check_range_support(self, file_url: str) -> tuple[bool, int]:
        """Check if server supports range requests and get file size"""
        try:
            head_response = self.session.head(file_url, timeout=10)
            file_size = int(head_response.headers.get('content-length', 0))
            accept_ranges = head_response.headers.get('accept-ranges', '').lower()
            supports_ranges = accept_ranges == 'bytes'
            return supports_ranges, file_size
        except:
            return False, 0
    
    def download_chunk(self, file_url: str, start: int, end: int, chunk_file: Path) -> bool:
        """Download a specific chunk of a file"""
        for attempt in range(self.max_retries):
            try:
                headers = {'Range': f'bytes={start}-{end}'}
                response = self.session.get(file_url, headers=headers, timeout=30, stream=True)
                
                if response.status_code == 206:  # Partial Content
                    with open(chunk_file, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    return True
                else:
                    raise Exception(f"Server returned status {response.status_code}")
                    
            except Exception as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"⚠ Chunk {start}-{end} attempt {attempt + 1}/{self.max_retries} failed: {e}")
                    time.sleep(wait_time)
                else:
                    print(f"✗ Chunk {start}-{end} failed after {self.max_retries} attempts: {e}")
                    return False
        return False
    
    def download_file_chunked(self, file_url: str, local_path: Path) -> bool:
        """Download a file using multiple chunks in parallel"""
        supports_ranges, file_size = self.check_range_support(file_url)
        
        if not supports_ranges or file_size == 0:
            print(f"⚠ Server doesn't support range requests, falling back to single thread: {local_path.name}")
            return self.download_file_single(file_url, local_path)
        
        # Check if file is already complete
        if local_path.exists() and local_path.stat().st_size == file_size:
            print(f"✓ Skipped (complete): {local_path}")
            return True
        
        chunk_size = self.chunk_size_mb * 1024 * 1024  # Convert MB to bytes
        num_chunks = (file_size + chunk_size - 1) // chunk_size
        
        print(f"⚡ Chunked download: {local_path.name} ({file_size} bytes, {num_chunks} chunks)")
        
        # Create temp directory for chunks
        temp_dir = local_path.parent / f".{local_path.name}.chunks"
        temp_dir.mkdir(exist_ok=True)
        
        try:
            # Download chunks in parallel
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = []
                
                for i in range(num_chunks):
                    start = i * chunk_size
                    end = min(start + chunk_size - 1, file_size - 1)
                    chunk_file = temp_dir / f"chunk_{i:04d}"
                    
                    # Skip if chunk already exists and is complete
                    if chunk_file.exists() and chunk_file.stat().st_size == (end - start + 1):
                        continue
                    
                    future = executor.submit(self.download_chunk, file_url, start, end, chunk_file)
                    futures.append((future, i, start, end, chunk_file))
                
                # Wait for all chunks to complete
                for future, chunk_idx, start, end, chunk_file in futures:
                    success = future.result()
                    if not success:
                        return False
            
            # Merge chunks into final file
            print(f"🔗 Merging chunks: {local_path.name}")
            with open(local_path, 'wb') as output_file:
                for i in range(num_chunks):
                    chunk_file = temp_dir / f"chunk_{i:04d}"
                    if chunk_file.exists():
                        with open(chunk_file, 'rb') as chunk:
                            output_file.write(chunk.read())
                        chunk_file.unlink()  # Remove chunk file
            
            # Clean up temp directory
            temp_dir.rmdir()
            
            # Verify file size
            if local_path.stat().st_size == file_size:
                print(f"✓ Chunked download complete: {local_path}")
                return True
            else:
                print(f"✗ File size mismatch: {local_path}")
                return False
                
        except Exception as e:
            print(f"✗ Chunked download failed: {local_path}: {e}")
            # Clean up on failure
            try:
                import shutil
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
            except:
                pass
            return False
    
    def download_file_single(self, file_url: str, local_path: Path) -> bool:
        """Download a single file with resume support and retry mechanism (single thread)"""
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
    
    def download_file(self, file_url: str, local_path: Path) -> bool:
        """Download a single file - chooses chunked or single thread based on settings"""
        if self.chunked_download:
            return self.download_file_chunked(file_url, local_path)
        else:
            return self.download_file_single(file_url, local_path)
    
    def get_all_files_recursive(self, url: str, relative_path: str = "") -> List[tuple[str, str]]:
        """Recursively get all files from directory and subdirectories"""
        files_to_download = []
        
        print(f"Scanning: {url}")
        files, directories = self.parse_directory_listing(url)
        
        # Add files in current directory
        for file in files:
            file_url = urljoin(url + '/', file)
            # Decode URL-encoded filenames for local storage
            decoded_file = unquote(file)
            local_file_path = os.path.join(relative_path, decoded_file)
            files_to_download.append((file_url, local_file_path))
        
        # Recursively scan subdirectories
        for directory in directories:
            subdir_url = urljoin(url + '/', directory + '/')
            # Decode URL-encoded directory names for local storage
            decoded_directory = unquote(directory)
            subdir_relative_path = os.path.join(relative_path, decoded_directory)
            subdir_files = self.get_all_files_recursive(subdir_url, subdir_relative_path)
            files_to_download.extend(subdir_files)
        
        return files_to_download
    
    def is_direct_file_url(self, url: str) -> bool:
        """Check if URL points to a direct file (not a directory listing)"""
        try:
            response = self.session.head(url, timeout=10)
            content_type = response.headers.get('content-type', '').lower()
            
            # If it's HTML, it's likely a directory listing
            if 'text/html' in content_type:
                return False
            
            # If it has a content-length and is not HTML, it's likely a file
            if response.headers.get('content-length'):
                return True
                
            # If HEAD doesn't work, try GET with range to check
            try:
                response = self.session.get(url, headers={'Range': 'bytes=0-0'}, timeout=10)
                return response.status_code in [206, 200]  # Supports range or returns content
            except:
                return False
                
        except:
            return False
    
    def download_all(self, target_folder: str = ""):
        """Download all files from the target folder recursively or single file"""
        # If no target_folder, check if base_url is a direct file
        if not target_folder:
            if self.is_direct_file_url(self.base_url):
                # Direct file download from base URL
                print(f"Direct file download: {self.base_url}")
                print(f"Output directory: {self.output_dir.absolute()}")
                print(f"Max workers: {self.max_workers}")
                print("-" * 50)
                
                # Extract filename from URL and decode URL encoding
                filename = unquote(self.base_url.split('/')[-1])
                if not filename or '.' not in filename:
                    filename = "downloaded_file"
                
                local_path = self.output_dir / filename
                start_time = time.time()
                
                success = self.download_file(self.base_url, local_path)
                
                elapsed_time = time.time() - start_time
                print("\n" + "=" * 50)
                print(f"Download completed in {elapsed_time:.2f} seconds")
                
                if success:
                    print(f"Successfully downloaded: {filename}")
                    self.downloaded_files.add(str(local_path))
                else:
                    print(f"Failed to download: {filename}")
                    self.failed_downloads.append(self.base_url)
                
                return
        
        start_url = urljoin(self.base_url + '/', target_folder)
        
        # Check if this is a direct file URL
        if target_folder and not target_folder.endswith('/'):
            if self.is_direct_file_url(start_url):
                # Direct file download
                print(f"Direct file download: {start_url}")
                print(f"Output directory: {self.output_dir.absolute()}")
                print(f"Max workers: {self.max_workers}")
                print("-" * 50)
                
                # Extract filename from URL and decode URL encoding
                filename = unquote(target_folder.split('/')[-1])
                if not filename:
                    filename = "downloaded_file"
                
                local_path = self.output_dir / filename
                start_time = time.time()
                
                success = self.download_file(start_url, local_path)
                
                elapsed_time = time.time() - start_time
                print("\n" + "=" * 50)
                print(f"Download completed in {elapsed_time:.2f} seconds")
                
                if success:
                    print(f"Successfully downloaded: {filename}")
                    self.downloaded_files.add(str(local_path))
                else:
                    print(f"Failed to download: {filename}")
                    self.failed_downloads.append(start_url)
                
                return
        
        # Directory listing download (original behavior)
        if target_folder and not start_url.endswith('/'):
            start_url += '/'
        
        # Extract folder name from URL for creating subdirectory
        if not target_folder:
            # Get folder name from base URL
            folder_name = unquote(self.base_url.rstrip('/').split('/')[-1])
        else:
            # Get folder name from target_folder
            folder_name = unquote(target_folder.rstrip('/').split('/')[-1])
        
        # Create subdirectory in output folder
        if folder_name and folder_name != '.':
            final_output_dir = self.output_dir / folder_name
            final_output_dir.mkdir(parents=True, exist_ok=True)
            print(f"Starting download from: {start_url}")
            print(f"Output directory: {final_output_dir.absolute()}")
            print(f"Max workers: {self.max_workers}")
            print("-" * 50)
        else:
            final_output_dir = self.output_dir
            print(f"Starting download from: {start_url}")
            print(f"Output directory: {final_output_dir.absolute()}")
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
                local_path = final_output_dir / local_file_path
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
    parser.add_argument("-c", "--chunked", action="store_true", help="Enable chunked downloads for individual files")
    parser.add_argument("--chunk-size", type=int, default=10, help="Chunk size in MB for chunked downloads (default: 10)")
    
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
            max_retries=args.retries,
            chunked_download=args.chunked,
            chunk_size_mb=args.chunk_size
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