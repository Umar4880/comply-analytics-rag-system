from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from pathlib import Path
import io

class DriveDocumentDownloader:
    def __init__(self, service_account_key: str):
        credentials = Credentials.from_service_account_file(
            service_account_key,
            scopes=['https://www.googleapis.com/auth/drive']
        )
        self.drive_service = build('drive', 'v3', credentials=credentials)
    
    def download_file(self, file_id: str, output_path: str):
        """Download actual PDF file from Drive."""
        request = self.drive_service.files().get_media(fileId=file_id)
        with open(output_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
        return output_path
    
    def list_files_in_folder(self, folder_id: str):
        """List all PDFs in a Drive folder."""
        query = f"'{folder_id}' in parents and mimeType='application/pdf'"
        results = self.drive_service.files().list(q=query, spaces='drive').execute()
        return results.get('files', [])
    
    def get_file_metadata(self, file_id: str):
        meta = self.drive_service.files().get(
            fileId = file_id,
            fields="id,name,mimeType,size,createdTime,modifiedTime,md5Checksum,version,trashed,parents"
        ).execute()

        return meta

# # Usage:
# downloader = DriveDocumentDownloader(
#     service_account_key=str(Path.home() / ".credentials" / "keys.json")
# )

# # Get list of PDFs
# files = downloader.list_files_in_folder("YOUR_FOLDER_ID")

# for file in files:
#     # Download actual PDF file
#     pdf_path = f"/tmp/{file['name']}"
#     downloader.download_file(file['id'], pdf_path)
    
#     # Feed to your parser (which expects actual PDF on disk)
#     parser = DocumentParser(pdf_path)
#     parsed = parser.parse()
    
#     print(f"Parsed {file['name']}: {len(parsed.structured_chunks)} sections")