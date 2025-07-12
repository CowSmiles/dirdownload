# 🚀 Nginx Directory Downloader

A high-performance, multi-threaded Python tool for downloading entire directory trees from nginx web servers. Features intelligent resume capabilities, chunked downloads, and robust error handling for efficient bulk file downloads.

## ✨ Features

### 🏃 **High Performance**
- **Multi-threaded downloads** with configurable thread count (default: 8)
- **Chunked downloads** for individual large files using parallel connections
- **Session reuse** for optimal HTTP connection management
- **Concurrent directory scanning** for faster file discovery

### 📁 **Complete Directory Support**
- **Recursive traversal** of nested folder structures
- **Automatic nginx listing parsing** using BeautifulSoup
- **Preserves original directory structure** locally
- **Supports mounted SMB/CIFS shares** as output destinations

### 🔄 **Smart Resume & Recovery**
- **Automatic resume** for interrupted downloads using HTTP Range requests
- **File integrity checking** - compares local vs remote file sizes
- **Intelligent skip logic** - avoids re-downloading complete files
- **Graceful interruption handling** - stop and restart anytime
- **Retry mechanism** with exponential backoff (default: 5 retries)

### 📊 **Progress Tracking & Monitoring**
- **Real-time progress indicators** showing completed/total files
- **Detailed status messages** with visual indicators (✓ ⟳ ✗ ⚡ 🔗)
- **Download statistics** including timing and success rates
- **Failed download reporting** for troubleshooting

### 🛡️ **Robust Error Handling**
- **Configurable retry attempts** with exponential backoff
- **Timeout protection** (30s for downloads, 10s for HEAD requests)
- **HTTP error handling** with proper status code management
- **Network failure recovery** with detailed error reporting
- **Graceful degradation** when servers don't support advanced features

## 🔧 Installation

### Using uv (Recommended)
```bash
# Clone or create project directory
git clone <repository-url>
cd nginx-directory-downloader

# Install dependencies with uv
uv sync
```

### Using Traditional pip
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install requests beautifulsoup4
```

### Dependencies
- **Python 3.7+**
- **requests** - HTTP library for downloads
- **beautifulsoup4** - HTML parsing for directory listings

## 📖 Usage

### Basic Usage
```bash
# Download entire directory
uv run python downloader.py http://example.com/files/

# Download specific subfolder
uv run python downloader.py http://example.com/files/ -f "documents"

# Download single file directly
uv run python downloader.py http://example.com/files/movie.mp4

# Download to specific output directory
uv run python downloader.py http://example.com/files/ -o "/path/to/downloads"
```

### Advanced Options
```bash
# High-performance download with custom settings
uv run python downloader.py http://files.example.com/ \
    --folder "software/releases" \
    --output "/home/user/downloads" \
    --threads 16 \
    --retries 10 \
    --chunked \
    --chunk-size 50

# Single large file with chunked download
uv run python downloader.py http://example.com/bigfile.zip -c --chunk-size 100 -t 16

# Direct file download to mounted SMB share
uv run python downloader.py http://server.com/movie.mkv -c -o "/mnt/videos"
```

### SMB/Network Share Support
```bash
# Mount SMB share first
sudo mount -t cifs //192.168.1.100/videos /mnt/videos -o username=user

# Download to mounted share
uv run python downloader.py http://example.com/files/ -o "/mnt/videos"
```

### Command Line Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `url` | - | Base URL of nginx server (required) | - |
| `--folder` | `-f` | Target folder relative to base URL | `""` (root) |
| `--output` | `-o` | Local output directory or mount point | `downloads` |
| `--threads` | `-t` | Number of download threads | `8` |
| `--retries` | `-r` | Maximum retry attempts per file | `5` |
| `--chunked` | `-c` | Enable chunked downloads for large files | `false` |
| `--chunk-size` | - | Chunk size in MB for chunked downloads | `10` |

## 🎯 Download Modes

### Directory Mode (Default)
- **File-level parallelism**: Downloads multiple different files simultaneously
- **Best for**: Many small-to-medium files, servers with connection limits
- **Example**: 8 threads = 8 different files downloading at once
- **Usage**: `uv run python downloader.py http://example.com/files/`

### Single File Mode
- **Direct file download**: Automatically detects and downloads individual files
- **Supports all features**: Resume, chunked downloads, retries
- **Best for**: Large individual files, specific file downloads
- **Usage**: `uv run python downloader.py http://example.com/bigfile.zip`

### Chunked Mode (`-c` flag)
- **Chunk-level parallelism**: Splits large files into chunks for parallel download
- **Best for**: Large files, high-bandwidth connections, Range-supporting servers
- **Example**: 8 threads = 8 chunks of the same file downloading in parallel
- **Usage**: Add `-c` flag to any command above

## 📋 Example Output

### Directory Download
```
Starting download from: http://example.com/files/documents/
Output directory: /home/user/downloads
Max workers: 8
--------------------------------------------------
Scanning: http://example.com/files/documents/
Scanning: http://example.com/files/documents/pdfs/

Found 127 files to download
--------------------------------------------------
✓ Downloaded: downloads/documents/readme.txt
⟳ Resuming: downloads/documents/partial-file.zip (from 5242880 bytes)
✓ Resumed: downloads/documents/partial-file.zip
Progress: 127/127 files
==================================================
Download completed in 45.23 seconds
Successfully downloaded: 127 files
```

### Single File Download with Chunked Mode
```
Direct file download: http://example.com/movie.mkv
Output directory: /home/user/downloads
Max workers: 8
--------------------------------------------------
⚡ Chunked download: movie.mkv (5368709120 bytes, 512 chunks)
🔗 Merging chunks: movie.mkv
✓ Chunked download complete: movie.mkv
==================================================
Download completed in 89.45 seconds
Successfully downloaded: movie.mkv
```

## 🔍 Status Indicators

| Symbol | Meaning |
|--------|---------|
| `✓` | Successfully downloaded or completed |
| `⟳` | Resuming partial download |
| `⚡` | Starting chunked download |
| `🔗` | Merging downloaded chunks |
| `⚠` | Warning or retry attempt |
| `✗` | Failed download |

## 🏗️ Technical Details

### Resume Mechanism
1. **File Check**: Compares local file size with remote `Content-Length` header
2. **Range Request**: Uses `Range: bytes=X-` header for partial downloads
3. **Status Handling**: Properly handles HTTP 206 (Partial Content) and 200 (OK) responses
4. **Append Mode**: Seamlessly continues writing to existing files

### Chunked Download Process
1. **Range Support Detection**: Checks server `Accept-Ranges` header
2. **File Splitting**: Divides file into configurable chunks (default 10MB)
3. **Parallel Download**: Downloads chunks simultaneously using thread pool
4. **Chunk Verification**: Validates individual chunk completeness
5. **File Assembly**: Merges chunks in correct order
6. **Integrity Check**: Verifies final file size matches expected

### Directory Parsing
- Parses standard nginx autoindex HTML output
- Distinguishes files from directories using trailing slash detection
- Filters out navigation links (`../`, external URLs, query parameters)
- Handles URL encoding and special characters properly

### Performance Optimizations
- **Connection Pooling**: Reuses HTTP connections via `requests.Session`
- **Streaming Downloads**: Uses chunked reading to minimize memory usage
- **Parallel Processing**: Concurrent downloads with `ThreadPoolExecutor`
- **Smart Skipping**: Avoids unnecessary network requests for complete files
- **Exponential Backoff**: Intelligent retry timing to handle server load

## 🎯 Use Cases

### Perfect For
- **Backup nginx file servers** - Full site mirroring with resume support
- **Software distribution** - Download release archives and documentation  
- **Media collections** - Bulk download images, videos, audio files
- **Documentation sites** - Offline copies of static documentation
- **Development assets** - Download build artifacts and dependencies
- **Data archival** - Preserving web-hosted file collections

### Optimized Scenarios
- **High-latency connections** - Resume capability handles interruptions
- **Bandwidth-limited environments** - Configurable thread counts
- **Large file repositories** - Chunked downloads for maximum throughput
- **Network shares** - Direct download to SMB/CIFS mounted directories
- **Automated backups** - Robust error handling for unattended operations

## 🔧 Configuration Tips

### Performance Tuning
```bash
# For fast connections with large single files
uv run python downloader.py http://example.com/bigfile.zip -c --threads 16 --chunk-size 50

# For directories with many small files  
uv run python downloader.py http://example.com/files/ --threads 4 --retries 10

# For unstable connections
uv run python downloader.py http://example.com/files/ --retries 10 --chunk-size 5

# Maximum performance for large files
uv run python downloader.py http://example.com/movie.mkv -c -t 32 --chunk-size 100
```

### Network Share Optimization
```bash
# Mount with optimal settings for bulk downloads
sudo mount -t cifs //server/share /mnt/downloads \
    -o username=user,cache=strict,rsize=1048576,wsize=1048576
```

## 🐛 Troubleshooting

### Common Issues

**Connection Timeouts**
```bash
# Increase retry attempts for unstable connections
python downloader.py http://example.com/files/ -r 10
```

**Server Doesn't Support Chunked Downloads**
```
⚠ Server doesn't support range requests, falling back to single thread
```
This is normal - the tool automatically falls back to standard downloads.

**Permission Denied on SMB**
```bash
# Ensure proper mount permissions
sudo mount -t cifs //server/share /mnt/downloads -o username=user,uid=$(id -u),gid=$(id -g)
```

**Memory Usage with Large Files**
- Chunked mode uses minimal memory regardless of file size
- Each chunk is processed individually and discarded after writing

## 🤝 Compatibility

### Server Compatibility
- **Nginx autoindex** - Primary target with full feature support
- **Apache mod_autoindex** - Basic compatibility for directory listings
- **HTTP/1.1 servers** - Any server supporting standard HTTP features
- **Range request support** - Required for chunked downloads and resume

### Platform Support
- **Linux** - Full support including SMB mounting
- **macOS** - Full support with native SMB client
- **Windows** - Full support with mapped network drives
- **Docker/Containers** - Works in containerized environments

## 📄 License

MIT License - Feel free to use in personal and commercial projects.

## 🙏 Contributing

Contributions welcome! Please feel free to submit issues and pull requests.

### Development Setup
```bash
git clone <repository-url>
cd nginx-directory-downloader
uv sync
uv run python downloader.py --help
```

---

**Made with ❤️ for efficient bulk downloads**