# CELL 0 : Import `logging`
# THIS CELL - `logging` - MUST BE FIRST TO WORK CORRECTLY!
# LOGGING NEEDS TO BE THE FIRST IMPORT
import logging                # For printing informative messages during execution
import sys                    # For system-specific functions (like exiting)
import datetime

# Create a new log file for each run using a timestamp:
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
logging_filename = f'SheetExtractor_ExecutionLog_{timestamp}.log'
file_mode = 'w'

# ===================================================================================================
# === Logging Setup ===
# ===================================================================================================
# 1. Get the root logger (or a specific logger)
# Using root logger here to capture logs from module-level logging calls like logging.info()
logger = logging.getLogger()
logger.setLevel(logging.INFO) # Set the minimum level for the logger itself

# 2. Clear existing handlers (important in notebooks, similar effect to force=True)
if logger.hasHandlers():
    logger.handlers.clear()

# 3. Create a formatter
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')

# 4. Create a File Handler
file_handler = logging.FileHandler(logging_filename, mode=file_mode)
file_handler.setLevel(logging.INFO) # Set level for this handler
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler) # Add handler to the logger

# 5. Create a Console/Stream Handler (Optional - for simultaneous console output)
console_handler = logging.StreamHandler(sys.stdout) # Output to notebook cell
console_handler.setLevel(logging.INFO) # Or set a different level for console if desired
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

# Test the logging
logging.info(f"Logging initialized. Output to console and to: {logging_filename}")


# ===================================================================================================
# === Logging Setup ===
# ===================================================================================================
# Configure basic logging, forcing it to overwrite previous handlers
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s',
#     force=True,  # <--- Add this
#     stream=sys.stdout # <--- Explicitly direct to notebook stdout
# )

# # Test immediately after configuration
# logging.info("Logging configured successfully.")


# CELL 0.5 : Install Packages
# This installs the basic software tools the script needs to work. It's like getting the right apps ready before you start.
# Commented out IPython magic to ensure Python compatibility.
# Install necessary packages quietly (-q)
pip install -q pydantic Pillow google-genai

print("Required packages installed.")


# CELL 1 : Import Libraries
# This loads the specific commands and features the script will use. It's like opening the tools we need so they're ready to go.

import os                     # For interacting with the operating system (paths, directories)
import shutil                 # For high-level file operations (finding tools, removing directories)
import subprocess             # For running external command-line tools (Ghostscript, PDFtk)
import tempfile               # For creating temporary files and directories
import uuid                   # For generating unique IDs (for temporary folders)
import glob                   # For finding files matching a pattern (like images)
import re                     # For regular expressions (used in sorting image names)
import time                   # For timing operations
import json                   # For working with JSON data (AI response)
from pathlib import Path      # For easier path manipulation (recommended over os.path)
from typing import List, Dict, Any # For type hinting (improves code clarity)

# Image handling
from PIL import Image         # Pillow library for image operations

# Google AI / Gemini
from google import genai
from google.genai import types as genai_types # Use alias to avoid conflict with 'types' module

# Pydantic for data validation
from pydantic import BaseModel, Field

# Colab specific for secrets, Drive, and file uploads
try:
    from google.colab import drive, userdata, files
    COLAB_ENV = True
    drive.mount("/content/drive") # Mount Google Drive
except ImportError:
    print("WARNING: Not running in Colab or Colab modules failed to import. File upload/Drive access may fail.")
    COLAB_ENV = False
    # Define dummy variables if not in Colab, so later checks don't fail
    userdata = None
    files = None

# ===================================================================================================
# === Pydantic Models (Expected JSON Structure) ===
# ===================================================================================================
# Define the structure Gemini should return
# ===================================================================================================
class PageDetail(BaseModel):
    page_number: int = Field(description="The page number in the document where this information was found.")
    sheet_number: str = Field(description="The sheet number extracted from the title block of the page (e.g., 'CS', 'C2.1', 'A-101').")
    sheet_title: str = Field(description="The sheet title, in Title Case, and sanitized using the provided sanitization rules. Extracted from the title block of the page. For example: 'Demolition Plan', 'Cover Sheet', 'Sesc Plan 1 of 6'.")

class ExtractedData(BaseModel):
    total_num_pages_all_parts: int = Field(description="The total number of pages represented by the input images.")
    pages: List[PageDetail] = Field(description="A list of bookmark entries, one for each page/image processed, ORDERED by page_number.")

print("Libraries imported & Pydantic strcuture defined.")


# CELL 2 : Configuration and Logging Setup
# This sets up the main settings, like where to save the final file and the instructions for the AI. It also securely handles the AI password.
class AppConfig:
    """Holds all configuration settings for the application."""
# ===================================================================================================
# === 1. Output Settings ===
# ===================================================================================================
    # Base directory on Google Drive where the final bookmarked PDF and temp folders will be created.
    BASE_OUTPUT_DIR: str = "/content/drive/MyDrive/Apr11-Sheet-Extraction/"

# ===================================================================================================
# === 2. Gemini API Settings ===
# === DO NOT CHANGE THESE!
# ===================================================================================================
    # Attempt to get API key from Colab secrets first, then environment variable
    GEMINI_API_KEY: str | None = None
    if COLAB_ENV and userdata:
        GEMINI_API_KEY = userdata.get('GOOGLE_API_KEY')
    if not GEMINI_API_KEY:
         GEMINI_API_KEY = os.getenv('GOOGLE_API_KEY')
    # Add a default placeholder if you want, but raising an error later if None is safer
    # if not GEMINI_API_KEY:
    #     GEMINI_API_KEY = "YOUR_API_KEY_HERE" # Replace if not using secrets/env vars

    GEMINI_MODEL_NAME: str = "gemini-2.5-pro-exp-03-25"
    GEMINI_TEMPERATURE: float = 0.0

# ===================================================================================================
# === 3. Ghostscript Settings ===
# ---------------------------------------------------------------------------------------------------
# === NOTE: GS_RESOLUTION value controls the resolution of the images created from the PDF.         #
# === DON'T SET GS_RESOLUTION UNDER 80                                                              #
    GS_RESOLUTION: int = 120                                                                        #
# ---------------------------------------------------------------------------------------------------
# === NOTE: GS_IMAGE_FORMAT value should be left as 'pnggray'                                       #
    GS_IMAGE_FORMAT: str = 'pnggray'                                                                #
# ===================================================================================================

# ===================================================================================================
# === 4. System Prompt for Gemini (aka System Instructions) ===
# ===================================================================================================
    GEMINI_SYSTEM_PROMPT_TEMPLATE: str = """<ROLE>

**You are an expert at finding and extracting** a `sheet_number` (aka sheet no. or plan no., etc.) and a `sheet_title` **from within the 'Title Block' of each page** (each page being an image) of a construction drawings/plans document.
    * You must first identify the 'Title Block' area.
    * DO NOT use data from the center of the page. **This is not the 'Title Block'**.

</ROLE>

<CONTEXT>

* You are processing **exactly {actual_total_pages} pages of a construction drawings document** that has been converted to {actual_total_pages} single-page images.
    * The images are provided sequentially below.
* Note: While the 'Title Block' contains the required information, its exact visual layout, positioning of elements, or surrounding
text might vary in different parts of the document set. As a hypothetical example:
    * Pgs1-49 might use 'Title_Block_Layout_1', while Pgs 50-100 might use 'Title_Block_Layout_2', etc.
    * **Title Blocks are always found on the bottom edge or right-side edge of each page**, with **`sheet_number` and `sheet_title` generally appearing along the
right-side edge or in the lower-right corner**.
    * **DO NOT use data from the top or center of the page** even if you believe it's the `sheet_title` as this data is incorrect.
    * Focus on identifying the semantic meaning of `sheet_number` and `sheet_title` within the title block area, regardless of minor layout shifts. Including:
        * Patterns in the structure of the `sheet_number` and how it relates to the corresponding `sheet_title`.

</CONTEXT>

<TERM_DEFINITIONS>

(FYI: Terms can vary slightly in these documents!)

1. `sheet_number` (aka 'Sheet No.' or similar) is the plan or drawing number and **found in the title block** on each page (image).
    * `sheet_number` hypothetical format/structure examples:
        * 'A1.1'
        * 'M2.0S1'
        * 'M-304'
        * 'S200'
        * 'A0-CS2'
        * 'BA-101'
        * There are many other alphanumerical (including decimals and hyphens) combinations!
2. `sheet_title` (aka 'Plan Title', 'Drawing Title', or similar) is the name of each Drawing/Plan and is **found in the title block** on each page (image).
    * `sheet_title` hypothetical format/structure examples:
        * '2nd Floor Plan - Area A'
        * '1st Floor Reflected Ceiling Plan'
        * 'Mechanical Schedules'
        * 'Plan and Profile'
        * More examples below!
    * ALWAYS sanitize `sheet_title` data using a combination of the following '**SANITIZATION RULES (for `sheet_title` JSON output)**':
        1. Symbols & Punctuation:
            - '-' is the only symbol allowed in the final `sheet_title` data in the JSON output.
            - '/' and '\\' in the document, become '-' in the JSON output.
            - '&' in the document, becomes 'and' in the JSON output.
            - ',', '.', and '#' in the document, are removed in the JSON output.
            - '(', ')', '[', ']', '{{', and '}}' in the document, are removed in the JSON output while keeping the enclosed text.
        2. VERY IMPORTANT (to avoid failure):
            - **ALWAYS convert `sheet_title` to 'Title Case'**.
            - **Never output `sheet_title` in ALL CAPS**.
        3. Using pattern "*appearance in document* :: **sanitized data for JSON output**" here are some real-world sanitization examples:
            - *Detached Garage #2 & #3 Enlarged Electrical Plans* :: **Detached Garage 2 and 3 Enlarged Electrical Plans**
            - *1st, 2nd, & 3rd Floor Bldg. Plans / Notes* :: **1st 2nd and 3rd Floor Bldg Plans - Notes**
            - *Grading and SESC Plan (1 of 6)* :: **Grading and Sesc Plan 1 of 6**
            - *3rd FLOOR BUILDING PLANS* :: **3rd Floor Building Plans**
            - *1st Floor Partial Bldg. Plans - Units \\\"D8-H\\\" & \\\"T1-H\\\"* :: **1st Floor Partial Bldg Plans - Units D8-H and T1-H**

</TERM_DEFINITIONS>

<TASK>
1. You will analyze the provided pages (images) page by page (image by image), sequentially, covering all {actual_total_pages} pages.
2. For each page (image), determine the corresponding `page_number` (starting from 1 for the first image and incrementing sequentially up to {actual_total_pages} ).
3. Extract the Sheet Number and Sheet Title by visually reading the TITLE BLOCK within each page (image), disregard most if not all of the body of the pages.
4. Your output **MUST** be a single JSON **object** conforming to the specified response schema.
5. This JSON object must contain:
    * `total_num_pages_all_parts`: The total number of pages. This **MUST** equal {actual_total_pages}.
    * `pages`: A JSON array containing exactly {actual_total_pages} objects, one for each page/image processed.
        * Each object in this array must contain the `page_number`, `sheet_number`, and `sheet_title` for that specific page/image.
</TASK>

<KEYS_TO_SUCCESS>

These are your KEYS TO SUCCESS:
1. **NEVER make assumptions**
2. Every sheet number/title in your output JSON will use **REAL DATA that you visually read/extracted from the page images**
3. Do not include any bullet points, numbering, or extra commentary outside the JSON structure.
4. The `pages` array **MUST** contain exactly {actual_total_pages} entries, ordered sequentially by `page_number` starting from 1 and ending at {actual_total_pages}.
5. Ensure the value for `total_num_pages_all_parts` **MUST** be exactly {actual_total_pages}.
6. The data will be consistently located from page to page in most cases aside from cover/title sheets and oddball documents.
7. The first page (`page_number` = 1), if it's a cover/title sheet or list of drawings, will always have `sheet_number` "CS" or "TS", and `sheet_title` of "Cover Sheet" or "Title Sheet".
8. Always output "pretty-printed" human-readable JSON.

</KEYS_TO_SUCCESS>"""

# ===================================================================================================
# === 6. Create a Config Instance ===
# ===================================================================================================
# ‼️ We will use this 'config' object throughout the script to access settings ‼️
try:
    config = AppConfig()
    # Validate essential config like API key immediately
    if not config.GEMINI_API_KEY:
        raise ValueError("Gemini API Key not found in Colab secrets or environment variables.")
    logging.info("Application configuration loaded successfully.")
except Exception as e:
    logging.critical(f"Failed to initialize configuration: {e}")
    # Optionally exit if config is invalid
    # sys.exit(f"CRITICAL ERROR: Configuration failed - {e}")

print("Configuration class defined and instance created.")


# CELL 3: External Tool Finder Function
# This finds essential helper programs the script needs. If they're missing, it tries to install them automatically.

def find_executable(tool_name: str, common_names: List[str]) -> str:
    """
    Finds the executable path for a given tool using common names and the system PATH.
    Attempts installation via apt-get on Colab/Linux if not initially found.

    Args:
        tool_name: The generic name of the tool (for logging, e.g., "Ghostscript").
        common_names: A list of possible executable names (e.g., ["gs", "gswin64c"]).

    Returns:
        The absolute path to the first found executable.

    Raises:
        FileNotFoundError: If none of the common names for the executable can be found
                           in the system PATH, even after an installation attempt.
    """
    logging.info(f"Searching for {tool_name} executable (checking names: {common_names})...")
    for name in common_names:
        path = shutil.which(name)
        if path:
            logging.info(f"{tool_name} found as '{name}' at: {path}")
            return path # Return the path as soon as one is found

    # If the loop finishes without finding the tool initially
    logging.warning(f"{tool_name} not found in PATH using names: {common_names}.")
    error_msg = f"Required executable '{tool_name}' not found in system PATH using names: {common_names}." # Default error

    # Attempt installation if in Colab/Linux (optional, based on original script)
    install_attempted = False
    if COLAB_ENV and sys.platform.startswith("linux"):
        install_package = None
        if tool_name == "Ghostscript":
            install_package = "ghostscript"
        elif tool_name == "PDFtk":
            # Try pdftk-java first as it's common on newer systems
            install_package = "pdftk-java" # or just "pdftk" if that fails

        if install_package:
            install_attempted = True
            logging.warning(f"Attempting to install {tool_name} ({install_package}) via apt-get...")
            try:
                # Run update quietly first
                subprocess.run(['apt-get', 'update', '-qq'], check=True, capture_output=True, timeout=520)
                # Run install quietly
                subprocess.run(['apt-get', 'install', '-y', '-qq', install_package], check=True, capture_output=True, timeout=580)
                logging.info(f"Installation command for {install_package} completed.")
                # Check again after installation
                # For PDFtk, the command is usually just 'pdftk' regardless of package name
                check_name = "pdftk" if tool_name == "PDFtk" else common_names[0] # Check primary name
                path_after_install = shutil.which(check_name)
                if path_after_install:
                    logging.info(f"{tool_name} installed and found at: {path_after_install}")
                    return path_after_install # Success! Return the path
                else:
                     # If pdftk-java install didn't make 'pdftk' available, maybe try 'pdftk' package?
                     # (Add logic here if needed for fallback package install)
                     error_msg = f"{tool_name} installation attempted ({install_package}), but executable '{check_name}' still not found."
                     logging.error(error_msg)

            except subprocess.TimeoutExpired as time_e:
                 logging.error(f"Timeout during {tool_name} installation attempt: {time_e}")
                 error_msg = f"Timeout occurred while trying to install {tool_name}."
            except subprocess.CalledProcessError as install_e:
                logging.error(f"apt-get command failed during {tool_name} installation attempt: {install_e}")
                error_msg = f"Installation command failed for {tool_name}."
            except Exception as install_e:
                logging.error(f"Unexpected error during {tool_name} installation attempt: {install_e}")
                error_msg = f"An unexpected error occurred during {tool_name} installation."

    # If not found initially and either not Colab/Linux or install failed/didn't find it
    logging.error(error_msg) # Log the final error message
    raise FileNotFoundError(error_msg) # Raise the exception

print("External tool finder function 'find_executable' defined.")

# CELL 4: Path Management Function
# This creates a unique temporary folder for each PDF to keep working files organized. It also decides where the final bookmarked PDF will be saved.

def get_processing_paths(output_base_dir: str, original_filename: str) -> Dict[str, str]:
    """
    Generates and creates a unique set of paths for processing a single file.

    Creates a job-specific temporary directory within the base output directory
    to isolate intermediate files (images, JSON response, bookmark data).
    The final bookmarked PDF is saved directly in the base output directory.

    Args:
        output_base_dir: The base directory from AppConfig where outputs are stored.
        original_filename: The original name of the uploaded file.

    Returns:
        A dictionary containing string paths for various stages:
        'temp_dir': Path to the unique temporary directory for this job's intermediates.
        'image_output_dir': Subdirectory within temp_dir for generated images.
        'response_file_path': Path within temp_dir for storing the raw AI response JSON.
        'bookmark_file_path': Path within temp_dir for the generated PDFtk bookmark file.
        'final_output_path': Path for the final bookmarked PDF (in base_output_dir).

    Raises:
        OSError: If directory creation fails.
    """
    # Create a 'safe' version of the filename stem for use in directory names
    # Replace spaces and remove extension
    safe_base_filename = Path(original_filename).stem.replace(" ", "_").replace(".", "_")
    # Generate a short unique ID to prevent collisions even if processing the same file multiple times
    unique_id = uuid.uuid4().hex[:8]

    # Define the unique temporary directory for this processing job's intermediate files
    # Place it inside the main output directory for better organization during runs
    temp_dir = Path(output_base_dir) / f"processing_{safe_base_filename}_{unique_id}"

    # Define paths for intermediate files within the temporary directory
    image_output_dir = temp_dir / "images"
    response_file_path = temp_dir / f"{safe_base_filename}_response.json"
    bookmark_file_path = temp_dir / f"{safe_base_filename}_bookmarks.txt"

    # Define the final output path (saved directly in the base output dir, not temp)
    # Prepend "Autobookmarked_" to easily identify the final product
    final_output_filename = f"Autobookmarked_{original_filename}"
    final_output_path = Path(output_base_dir) / final_output_filename

    # Create the temporary directory and its image subdirectory
    try:
        # exist_ok=True prevents error if it somehow already exists (unlikely with UUID)
        os.makedirs(image_output_dir, exist_ok=True)
        # Also ensure the main output directory exists (important for final_output_path)
        os.makedirs(output_base_dir, exist_ok=True)
        logging.info(f"Created temporary processing directory for intermediates: {temp_dir}")
    except OSError as e:
        logging.error(f"Failed to create processing directories under {temp_dir}: {e}")
        raise # Re-raise the error as this is critical for the workflow

    # Store paths as strings in the dictionary (compatible with older functions/libraries)
    paths = {
        "temp_dir": str(temp_dir),
        "image_output_dir": str(image_output_dir),
        "response_file_path": str(response_file_path),
        "bookmark_file_path": str(bookmark_file_path),
        "final_output_path": str(final_output_path),
    }
    logging.info(f"Generated processing paths for '{original_filename}'.")
    return paths

print("Path management function 'get_processing_paths' defined.")

# CELL 5: Core Processing Functions (Parameterized)
# This defines the main steps: converting PDF pages to images, asking the AI to read them, formatting the AI's answer into bookmarks, and adding those bookmarks to the PDF.

# --- 1. PDF to Images Function ---
def pdf_to_images(pdf_path: str, output_dir: str, gs_path: str, resolution: int, image_format: str) -> List[str]:
    """
    Converts PDF pages to images using Ghostscript. (Adapted from original)

    Args:
        pdf_path: Path to the input PDF file.
        output_dir: Directory where output images will be saved (should exist).
        gs_path: Path to the Ghostscript executable.
        resolution: Output resolution in DPI.
        image_format: Ghostscript device format string (e.g., 'pnggray').

    Returns:
        A sorted list of absolute paths to the generated image files.

    Raises:
        FileNotFoundError: If the input PDF doesn't exist.
        ValueError: If gs_path is not provided.
        RuntimeError: If Ghostscript fails, times out, or produces no images.
        subprocess.CalledProcessError: If Ghostscript returns a non-zero exit code.
        subprocess.TimeoutExpired: If Ghostscript takes too long.
    """
    logging.info(f"Attempting PDF to image conversion for: {os.path.basename(pdf_path)}")
    if not os.path.exists(pdf_path):
         raise FileNotFoundError(f"Input PDF not found at: {pdf_path}")
    if not gs_path:
         raise ValueError("Ghostscript path is not provided.")

    # Determine file extension based on format
    if 'png' in image_format: ext = 'png'
    elif 'jpeg' in image_format or 'jpg' in image_format: ext = 'jpg'
    else: ext = 'img' # Fallback

    # Define the output pattern within the specific output_dir for this job
    output_pattern = os.path.join(output_dir, f"page_%04d.{ext}")

    # Construct the command
    command = [
        gs_path,
        "-dNOPAUSE",          # Don't pause between pages
        "-dBATCH",            # Exit after processing
        "-dSAFER",            # Run in sandbox mode
        "-q",                 # Suppress informational messages
        f"-sDEVICE={image_format}", # Set output format
        f"-r{resolution}",     # Set resolution
        f"-sOutputFile={output_pattern}", # Set output file pattern
        pdf_path              # Input PDF file
    ]

    try:
        logging.info(f"Running Ghostscript command: {' '.join(command)}")
        # Execute with a timeout (e.g., 5 minutes = 300 seconds)
        result = subprocess.run(command, capture_output=True, check=True, timeout=1200)
        # Log any stderr output from Ghostscript (often contains warnings or info)
        stderr_output = result.stderr.decode(errors='ignore')
        if stderr_output and stderr_output.strip():
             logging.debug(f"Ghostscript stderr: {stderr_output.strip()}")
        logging.info("Ghostscript conversion command executed successfully.")

        # Find the generated image files
        glob_pattern = os.path.join(output_dir, f"page_*.{ext}")
        image_files = glob.glob(glob_pattern)
        if not image_files:
            # This is an error condition - GS ran but produced nothing
            raise RuntimeError(f"Ghostscript ran successfully but no images found matching pattern '{glob_pattern}'. Check GS logs or input PDF.")

        # Sort the files numerically based on the page number in the filename
        def sort_key(filepath):
            # Use regex to extract the number part of 'page_NNNN.ext'
            match = re.search(r'page_(\d+)\.' + re.escape(ext) + '$', os.path.basename(filepath))
            # Return the integer page number if found, otherwise -1 for robust sorting
            return int(match.group(1)) if match else -1
        image_files.sort(key=sort_key)

        logging.info(f"Found and sorted {len(image_files)} image file(s) in {output_dir}.")
        return image_files # Return the sorted list of paths

    except subprocess.CalledProcessError as e:
        # Handle errors where Ghostscript itself reported failure (non-zero exit code)
        stderr = e.stderr.decode(errors='ignore') if e.stderr else 'N/A'
        stdout = e.stdout.decode(errors='ignore') if e.stdout else 'N/A'
        logging.error(f"Ghostscript failed. Command: '{e.cmd}'. Return code: {e.returncode}. Stderr: {stderr}")
        # Raise a more specific error indicating the source
        raise RuntimeError(f"Ghostscript conversion failed for {os.path.basename(pdf_path)}") from e
    except subprocess.TimeoutExpired:
         # Handle cases where Ghostscript took too long
         logging.error(f"Ghostscript command timed out after 300 seconds for {os.path.basename(pdf_path)}.")
         raise RuntimeError(f"Ghostscript timed out for {os.path.basename(pdf_path)}")
    except Exception as e:
        # Catch any other unexpected errors during the process
        logging.error(f"Unexpected error during Ghostscript conversion: {e}", exc_info=True)
        raise RuntimeError(f"Unexpected error during image conversion for {os.path.basename(pdf_path)}") from e

# --- 2. Generate Bookmarks Function ---
def generate_bookmarks_ai(client: genai.Client, model_name: str, temperature: float, system_prompt_template: str, image_paths: List[str], response_schema: BaseModel) -> Dict:
    """
    Generates bookmark data from images using the Gemini API. (Adapted from original)

    Args:
        client: Initialized Gemini API client instance.
        model_name: Name of the Gemini model to use.
        temperature: Temperature setting for the AI model.
        system_prompt_template: The template string for the system prompt,
                                containing '{actual_total_pages}'.
        image_paths: A list of paths to the image files (sorted).
        response_schema: The Pydantic model class defining the expected JSON structure.

    Returns:
        A dictionary representing the parsed JSON response from the AI.

    Raises:
        ValueError: If client or image_paths are invalid.
        RuntimeError: If image preparation, API call, or response parsing fails.
    """
    logging.info(f"Starting AI bookmark generation for {len(image_paths)} images.")
    if not client: raise ValueError("Gemini client is not provided.")
    if not image_paths: raise ValueError("No image paths provided for AI generation.")

    actual_total_pages = len(image_paths)
    image_parts = [] # List to hold prepared image data for the API

    # Prepare image parts (read bytes, determine MIME type)
    try:
        for i, path in enumerate(image_paths):
            if not os.path.exists(path):
                 logging.warning(f"Image file not found: {path}. Skipping.")
                 continue # Skip missing images

            mime_type = None
            try:
                # Use Pillow to reliably get the MIME type
                with Image.open(path) as img:
                    # Convert format (like 'PNG') to MIME ('image/png')
                    mime_type = Image.MIME.get(img.format.upper())
                    if not mime_type: # Fallback based on file extension if Pillow fails
                         ext = os.path.splitext(path)[1].lower()
                         if ext == ".png": mime_type = "image/png"
                         elif ext in [".jpg", ".jpeg"]: mime_type = "image/jpeg"
                         elif ext == ".webp": mime_type = "image/webp" # Add other supported types if needed
                         else: raise ValueError(f"Cannot determine MIME type for {path}")
            except Exception as img_e:
                logging.warning(f"Could not determine MIME type for {path}: {img_e}. Skipping file.")
                continue # Skip this image if we can't determine type

            # Read the image file as binary data
            with open(path, 'rb') as f: img_bytes = f.read()
            # Create a Gemini API 'Part' object from the bytes and MIME type
            image_parts.append(genai_types.Part.from_bytes(data=img_bytes, mime_type=mime_type))

        if not image_parts:
             # This happens if all images failed MIME type detection or were missing
             raise RuntimeError("No valid image parts could be prepared for the API call.")
        logging.info(f"Prepared {len(image_parts)} image parts for API.")

    except Exception as e:
        logging.error(f"Error preparing image parts: {e}", exc_info=True)
        raise RuntimeError("Failed during image preparation for AI.") from e

        # Format the system prompt with the actual number of pages

    try:
        # This is where the formatting happens
        formatted_system_prompt = system_prompt_template.format(actual_total_pages=actual_total_pages)
    except KeyError as e:
            logging.error(f"System prompt template is missing '{e}' placeholder.") # This is the error being logged
            raise ValueError("Invalid system prompt template.") from e

    # Configure the Gemini API call
    generate_content_config = genai_types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json", # Request JSON output
        response_schema=response_schema, # Tell Gemini the expected structure (Pydantic model)
        system_instruction=formatted_system_prompt,
    )

    # Make the API call
    try:
        logging.info(f"Calling Gemini model '{model_name}' with {len(image_parts)} images...")
        # Add a timeout to the API request (e.g., 20 minutes = 1200 seconds)
        response = client.models.generate_content(
            model=model_name,
            contents=image_parts, # Send the list of prepared image parts
            config=generate_content_config
        )

        # Check if the response is valid and contains text
        if not response or not hasattr(response, 'text') or not response.text:
             # Log details if the response is empty or blocked
             feedback = "N/A"
             finish_reason = "N/A"
             if response and hasattr(response, 'prompt_feedback'):
                  feedback = response.prompt_feedback
             if response and hasattr(response, 'candidates') and response.candidates:
                  finish_reason = response.candidates[0].finish_reason
             logging.error(f"Gemini API call succeeded but returned no text. Feedback: {feedback}, Finish Reason: {finish_reason}")
             raise RuntimeError("Gemini API returned no text content. It might have been blocked or empty.")

        logging.info("Gemini API call successful, attempting to parse JSON response.")

        # --- Clean and Parse JSON ---
        # Gemini might wrap the JSON in markdown fences (```json ... ```)
        raw_text = response.text
        # Find the first '{' and the last '}'
        start_index = raw_text.find('{')
        end_index = raw_text.rfind('}')

        if start_index == -1 or end_index == -1 or end_index < start_index:
             logging.error(f"Could not find valid JSON object boundaries in response: {raw_text[:200]}...") # Log beginning of text
             raise ValueError("Invalid JSON structure received from Gemini API (missing '{' or '}').")

        # Extract the potential JSON string
        json_core_string = raw_text[start_index : end_index + 1]

        # Parse the extracted string into a Python dictionary
        parsed_data = json.loads(json_core_string)
        logging.info("Successfully parsed JSON response from Gemini.")
        # You could add validation against the Pydantic schema here if needed:
        # try:
        #     ExtractedData.model_validate(parsed_data)
        #     logging.info("JSON response validated against Pydantic schema.")
        # except ValidationError as val_err:
        #     logging.error(f"JSON response failed Pydantic validation: {val_err}")
        #     raise ValueError("Gemini response did not match expected schema.") from val_err
        return parsed_data # Return the dictionary

    except Exception as e:
        # Catch errors from the API call or JSON parsing
        logging.error(f"Error during Gemini API call or response parsing: {e}", exc_info=True)
        # Check if it's a specific Gemini error type if needed
        # if isinstance(e, genai_types.StopCandidateException):
        #    logging.error("Gemini generation stopped potentially due to safety settings or other reasons.")
        raise RuntimeError("Gemini API interaction or response processing failed.") from e

# --- 3. Convert JSON to PDFtk Format Function ---
def convert_ai_response_to_pdftk(response_data: Dict, output_bmk_path: str) -> bool:
    """
    Converts the parsed AI response dictionary to PDFtk bookmark format text file.
    (Adapted from original)

    Args:
        response_data: The dictionary parsed from the AI's JSON response.
        output_bmk_path: The full path where the .txt bookmark file should be saved.

    Returns:
        True if conversion and saving were successful, False otherwise.
    """
    logging.info(f"Converting AI response dictionary to PDFtk format for: {output_bmk_path}")
    try:
        # Validate the structure of the response data
        if 'pages' not in response_data or not isinstance(response_data['pages'], list):
            logging.error("AI response JSON is missing the 'pages' list or it's not a list.")
            return False # Indicate failure

        pages_data = response_data['pages']
        if not pages_data:
             logging.warning("AI response contained an empty 'pages' list. No bookmarks to generate.")
             # Write an empty file to indicate no bookmarks, maybe? Or return False?
             # For now, let's treat it as success with no bookmarks.
             with open(output_bmk_path, 'w', encoding='utf-8') as f:
                 f.write("") # Write empty file
             return True


        pdftk_bookmarks = [] # List to hold formatted bookmark strings
        for page_detail in pages_data:
            try:
                # Extract required fields, handling potential missing keys gracefully
                page_num = page_detail['page_number']
                sheet_num = page_detail.get('sheet_number', 'MISSING_SHEET_NUM') # Use default if missing
                sheet_title = page_detail.get('sheet_title', 'MISSING_SHEET_TITLE') # Use default if missing

                # Combine sheet number and title for the bookmark text
                bookmark_title = f"{sheet_num} {sheet_title}"

                # Create the PDFtk bookmark entry string (ensure newline separation)
                bookmark_entry = f"BookmarkBegin\nBookmarkTitle: {bookmark_title}\nBookmarkLevel: 1\nBookmarkPageNumber: {page_num}\n\n"
                pdftk_bookmarks.append(bookmark_entry)
            except KeyError as e:
                # This happens if 'page_number' is missing (others have defaults)
                logging.warning(f"Skipping page entry due to missing required key 'page_number': {e}. Entry: {page_detail}")
                continue # Skip this malformed entry and proceed with the next
            except Exception as entry_e:
                 logging.warning(f"Error processing page entry: {entry_e}. Entry: {page_detail}")
                 continue # Skip problematic entries

        if not pdftk_bookmarks:
             logging.warning("No valid bookmark entries could be generated from the 'pages' data.")
             # Write an empty file if no valid entries were processed
             with open(output_bmk_path, 'w', encoding='utf-8') as f:
                 f.write("")
             return True # Still technically successful conversion (of nothing)

        # Join all formatted bookmark strings into one final string
        final_output_string = "".join(pdftk_bookmarks)

        # Write the final string to the output text file
        # Ensure the directory exists (should be handled by get_processing_paths)
        os.makedirs(os.path.dirname(output_bmk_path), exist_ok=True)
        with open(output_bmk_path, 'w', encoding='utf-8') as f:
            f.write(final_output_string)

        logging.info(f"Successfully saved PDFtk bookmarks ({len(pdftk_bookmarks)} entries) to {output_bmk_path}")
        return True # Indicate success

    except Exception as e:
        logging.error(f"Error converting AI response to PDFtk format: {e}", exc_info=True)
        return False # Indicate failure

# --- 4. Apply PDFtk Bookmarks Function ---
def apply_bookmarks(pdftk_path: str, input_pdf_path: str, bookmark_data_path: str, output_pdf_path: str) -> bool:
    """
    Applies bookmarks from a data file to a PDF using pdftk update_info.
    (Adapted from original)

    Args:
        pdftk_path: Path to the PDFtk executable.
        input_pdf_path: Path to the *original* input PDF file (the one to add bookmarks to).
        bookmark_data_path: Path to the text file containing PDFtk bookmark data.
        output_pdf_path: Path where the output PDF with bookmarks will be saved.

    Returns:
        True if pdftk command executed successfully and output file exists, False otherwise.

    Raises:
        ValueError: If pdftk_path is not provided.
        FileNotFoundError: If input_pdf_path or bookmark_data_path do not exist.
    """
    logging.info(f"Applying bookmarks from {os.path.basename(bookmark_data_path)} to {os.path.basename(input_pdf_path)}")
    if not pdftk_path: raise ValueError("PDFtk path is not provided.")
    if not os.path.exists(input_pdf_path): raise FileNotFoundError(f"Input PDF for bookmarking not found: {input_pdf_path}")
    if not os.path.exists(bookmark_data_path): raise FileNotFoundError(f"Bookmark data file not found: {bookmark_data_path}")

    # Construct the PDFtk command
    command = [
        pdftk_path,
        input_pdf_path,
        "update_info",       # Command to update metadata/bookmarks
        bookmark_data_path,  # The bookmark data file
        "output",
        output_pdf_path      # The final output file path
    ]

    try:
        logging.info(f"Running PDFtk command: {' '.join(command)}")
        # Execute with a timeout (e.g., 2 minutes = 120 seconds)
        result = subprocess.run(command, capture_output=True, check=True, text=True, encoding='utf-8', errors='ignore', timeout=120)

        # Log PDFtk output (often useful for debugging)
        stderr_output = result.stderr
        if stderr_output and stderr_output.strip(): logging.debug(f"PDFtk stderr: {stderr_output.strip()}")
        stdout_output = result.stdout
        if stdout_output and stdout_output.strip(): logging.debug(f"PDFtk stdout: {stdout_output.strip()}")

        # Verify that the output file was actually created and is not empty
        if os.path.exists(output_pdf_path) and os.path.getsize(output_pdf_path) > 0:
            logging.info(f"PDFtk bookmark application successful. Output saved to: {output_pdf_path}")
            return True # Indicate success
        else:
            # This is an error: command ran but didn't produce the expected output
            logging.error(f"PDFtk command ran but output file '{output_pdf_path}' was not created or is empty.")
            # Attempt to remove the empty file if it exists
            if os.path.exists(output_pdf_path):
                 try: os.remove(output_pdf_path)
                 except OSError: pass # Ignore error if removal fails
            return False # Indicate failure

    except subprocess.CalledProcessError as e:
        # Handle errors where PDFtk itself reported failure
        stderr = e.stderr if isinstance(e.stderr, str) else e.stderr.decode(errors='ignore') if e.stderr else 'N/A'
        stdout = e.stdout if isinstance(e.stdout, str) else e.stdout.decode(errors='ignore') if e.stdout else 'N/A'
        logging.error(f"PDFtk failed. Command: '{e.cmd}'. Return code: {e.returncode}. Stderr: {stderr}")
        return False # Indicate failure
    except subprocess.TimeoutExpired:
         # Handle cases where PDFtk took too long
         logging.error(f"PDFtk command timed out after 120 seconds for {os.path.basename(input_pdf_path)}.")
         return False # Indicate failure
    except Exception as e:
        # Catch any other unexpected errors
        logging.error(f"Unexpected error running PDFtk: {e}", exc_info=True)
        return False # Indicate failure

print("Core processing functions defined.")

# CELL 6: Workflow Orchestration Function
# This manages the entire process for one PDF, running the steps from Cell 5 in order. It also cleans up temporary files when finished.

def process_pdf_workflow(input_pdf_path: str, paths: Dict[str, str], gs_path: str, pdftk_path: str, client: genai.Client, config: AppConfig) -> str:
    """
    Orchestrates the PDF processing pipeline for a single file.

    Handles the sequence: PDF->Images->AI->Bookmarks->Apply.
    Ensures the temporary *processing* directory (containing images, json, bookmarks.txt)
    is cleaned up using a try...finally block, regardless of success or failure.

    Args:
        input_pdf_path: Path to the input PDF file (likely the temporary uploaded file).
        paths: Dictionary of paths generated by get_processing_paths.
        gs_path: Path to Ghostscript executable.
        pdftk_path: Path to PDFtk executable.
        client: Initialized Gemini API client.
        config: Application configuration object (AppConfig instance).

    Returns:
        Path (str) to the final bookmarked PDF file upon successful completion of all steps.

    Raises:
        Exception: Propagates exceptions from any failed step (e.g., RuntimeError,
                   FileNotFoundError, ValueError from the core functions).
                   The caller (handle_uploaded_pdf) should catch this.
    """
    # Get the path to the temporary directory created for this job's intermediates
    # We need this early so the 'finally' block can use it even if an error occurs before it's used
    temp_dir_to_clean = paths['temp_dir']
    logging.info(f"Starting PDF processing workflow for: {os.path.basename(input_pdf_path)}")
    logging.info(f"Intermediate files will be stored in: {temp_dir_to_clean}")
    logging.info(f"Final output target: {paths['final_output_path']}")

    try:
        # Step 1: Convert PDF to Images (using function from Cell 5)
        # Images are saved in paths['image_output_dir'] within the temp_dir
        image_paths = pdf_to_images(
            pdf_path=input_pdf_path,
            output_dir=paths['image_output_dir'],
            gs_path=gs_path,
            resolution=config.GS_RESOLUTION,
            image_format=config.GS_IMAGE_FORMAT
        )
        # pdf_to_images raises error on failure, so no need to check return value here

        # Step 2: Generate Bookmarks via AI (using function from Cell 5)
        ai_response_dict = generate_bookmarks_ai(
            client=client,
            model_name=config.GEMINI_MODEL_NAME,
            temperature=config.GEMINI_TEMPERATURE,
            system_prompt_template=config.GEMINI_SYSTEM_PROMPT_TEMPLATE,
            image_paths=image_paths,
            response_schema=ExtractedData # Pass the Pydantic model class from config
        )
        # generate_bookmarks_ai raises error on failure

        # Optional: Save raw AI response dictionary for debugging (within temp_dir)
        try:
             with open(paths['response_file_path'], 'w', encoding='utf-8') as f:
                 json.dump(ai_response_dict, f, indent=2)
             logging.info(f"Saved raw AI response JSON to {paths['response_file_path']}")
        except Exception as write_err:
             # Log as warning, don't fail the whole process if this write fails
             logging.warning(f"Could not write AI response file: {write_err}")


        # Step 3: Convert AI Response to PDFtk Format (using function from Cell 5)
        # Saves the bookmark data to paths['bookmark_file_path'] within temp_dir
        success = convert_ai_response_to_pdftk(
            response_data=ai_response_dict,
            output_bmk_path=paths['bookmark_file_path']
        )
        if not success:
            # Raise an error if conversion fails
            raise RuntimeError("Failed to convert AI response to PDFtk bookmark format.")

        # Step 4: Apply Bookmarks using PDFtk (using function from Cell 5)
        # Reads the original input PDF and the bookmark file from temp_dir,
        # writes the final output to paths['final_output_path'] (outside temp_dir)
        success = apply_bookmarks(
            pdftk_path=pdftk_path,
            input_pdf_path=input_pdf_path, # Apply to the original input PDF
            bookmark_data_path=paths['bookmark_file_path'],
            output_pdf_path=paths['final_output_path']
        )
        if not success:
            # Raise an error if applying bookmarks fails
            raise RuntimeError("Failed to apply PDFtk bookmarks to the PDF.")

        # If all steps above succeeded without raising an error:
        logging.info(f"Workflow completed successfully for {os.path.basename(input_pdf_path)}.")
        # Return the path to the final bookmarked PDF
        return paths['final_output_path']

    except Exception as e:
        # Catch any exception raised by the steps above
        logging.error(f"PDF processing workflow failed for {os.path.basename(input_pdf_path)}.")
        logging.error(f"Error details: {e}", exc_info=False) # Log basic error, set exc_info=True for full traceback
        # Re-raise the exception so the calling function (handle_uploaded_pdf) knows it failed
        raise

    finally:
        # Step 5: Cleanup Temporary Directory - THIS BLOCK *ALWAYS* RUNS
        logging.info(f"Initiating cleanup for temporary directory: {temp_dir_to_clean}")
        if temp_dir_to_clean and os.path.exists(temp_dir_to_clean):
            try:
                # Recursively remove the entire temporary directory and its contents
                shutil.rmtree(temp_dir_to_clean)
                logging.info(f"Successfully cleaned up temporary directory: {temp_dir_to_clean}")
            except OSError as e:
                # Log errors during cleanup, but don't raise again
                # to avoid masking the original error (if one occurred)
                logging.error(f"Error during temporary directory cleanup {temp_dir_to_clean}: {e}")
        else:
             # Log if the directory doesn't exist (maybe it failed to create or was already cleaned)
             logging.info("Temporary directory does not exist or was already cleaned up.")

print("Workflow orchestration function 'process_pdf_workflow' defined.")


# CELL 7: Upload Handler Function
# This handles the uploaded PDF file. It sets up the workspace and then tells the manager (Cell 6) to start the bookmarking process.

def handle_uploaded_pdf(uploaded_pdf_path: str, config: AppConfig, gs_path: str, pdftk_path: str, client: genai.Client) -> str | None:
    """
    Handles the end-to-end processing of a single uploaded PDF file.

    This acts as the primary entry point called by the main execution block
    (or potentially a UI backend). It coordinates path generation and
    calls the main processing workflow function.

    Args:
        uploaded_pdf_path: Path to the temporarily saved uploaded PDF file.
        config: The application configuration object (AppConfig instance).
        gs_path: Path to the Ghostscript executable.
        pdftk_path: Path to the PDFtk executable.
        client: Initialized Gemini API client instance.

    Returns:
        The absolute path (str) to the final bookmarked PDF file upon success,
        or None if any part of the processing workflow fails.
    """
    original_filename = os.path.basename(uploaded_pdf_path)
    logging.info(f"--- Starting processing request for file: {original_filename} ---")
    paths = None # Initialize in case path generation fails

    try:
        # 1. Generate unique paths for this processing job's intermediates and final output
        # This creates the temporary directory structure needed by the workflow
        paths = get_processing_paths(config.BASE_OUTPUT_DIR, original_filename)

        # 2. Execute the core processing pipeline by calling the workflow orchestrator
        # Pass the path to the uploaded file and all necessary tools/config
        final_pdf_path = process_pdf_workflow(
            input_pdf_path=uploaded_pdf_path, # Use the path of the uploaded file
            paths=paths,                      # Pass the generated paths dictionary
            gs_path=gs_path,
            pdftk_path=pdftk_path,
            client=client,
            config=config
        )

        # If process_pdf_workflow completes without raising an exception, it was successful
        logging.info(f"Successfully processed '{original_filename}'.")
        return final_pdf_path # Return the path to the final bookmarked PDF

    except Exception as e:
        # If process_pdf_workflow (or get_processing_paths) raised an exception, catch it here.
        # The error details should have already been logged within the workflow function.
        logging.error(f"Processing failed for '{original_filename}'. See previous logs for error details.")
        # The 'finally' block within process_pdf_workflow handles cleanup of the *processing* temp directory.
        # Return None to indicate to the caller (__main__ block or UI) that processing failed.
        return None
    # Note: Cleanup of the *initial* uploaded_pdf_path itself (the one passed into this function)
    # is the responsibility of the code that *calls* handle_uploaded_pdf (e.g., the __main__ block).

print("Upload handler function 'handle_uploaded_pdf' defined.")

# CELL 8: Main Execution Block (NEW STRATEGY)
# The next three cells (#8, 9, and 10) act as the "Start" button for the whole script. It checks everything, asks for the PDF upload, runs the process using the handler (from Cell 7), and reports the final result.

# Cell 8: Setup Before Upload
if __name__ == "__main__":
    if not COLAB_ENV:
        print("\nERROR: Requires Colab environment.")
        sys.exit(1)

    logging.info("=== Starting Main Execution Block ===")
    gs_path = None
    pdftk_path = None
    client = None
    # We will get temp_upload_path in the next cell

    try:
        # --- 1. Load Config ---
        logging.info("Using pre-loaded configuration.")
        if not config: raise RuntimeError("Configuration object 'config' not found.")

        # --- 2. Initialize Gemini Client ---
        logging.info("Initializing Gemini client...")
        if not config.GEMINI_API_KEY: raise ValueError("Gemini API Key is missing.")
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        logging.info("Gemini client initialized successfully.")

        # --- 3. Find Essential External Tools ---
        logging.info("Locating external tools (Ghostscript, PDFtk)...")
        gs_names = ["gs"] if sys.platform.startswith("linux") else ["gswin64c", "gswin32c", "gs"]
        pdftk_names = ["pdftk"]
        gs_path = find_executable("Ghostscript", gs_names)
        pdftk_path = find_executable("PDFtk", pdftk_names)
        logging.info("External tools located successfully.")

        # --- Ready for Upload ---
        logging.info("Setup complete. Proceed to the next cell to upload the PDF.")

    except Exception as setup_e:
        # Catch setup errors here
        logging.critical(f"CRITICAL ERROR during setup: {setup_e}", exc_info=True)
        # Prevent proceeding if setup failed
        raise RuntimeError("Setup failed, cannot proceed.") from setup_e


# CELL 9: File Upload
# This is where you'll upload a file (below this cell).

# Cell 9: File Upload
if __name__ == "__main__":
    # Make sure setup in the previous cell succeeded (variables should exist)
    if 'client' not in locals() or not client or not gs_path or not pdftk_path:
         logging.error("Setup variables not found. Please run the previous cell successfully first.")
         raise RuntimeError("Setup cell did not complete successfully.")

    uploaded = None # Initialize uploaded variable
    temp_upload_path = None # Initialize path variable

    # --- 4. Handle File Upload via Colab ---
    logging.info("="*20 + " PDF Upload " + "="*20)
    print("\nPlease upload the single PDF file you want to process:")
    try:
        uploaded = files.upload() # This widget will clear this cell's previous output
    except Exception as upload_e:
         logging.error(f"An error occurred during file upload: {upload_e}")
         # Handle potential errors during the upload process itself

    logging.info("="*52) # Separator after upload prompt finishes

    # --- Validate and Save Upload ---
    if uploaded:
        if len(uploaded) > 1:
            logging.error("Multiple files uploaded. Please run again and upload only one PDF.")
            # Clean up? Might be hard here. Best to just error out.
            raise ValueError("Multiple files uploaded.")
        if len(uploaded) == 1:
            uploaded_filename = list(uploaded.keys())[0]
            uploaded_content = uploaded[uploaded_filename]

            if not uploaded_filename.lower().endswith(".pdf"):
                logging.error(f"Uploaded file '{uploaded_filename}' is not a PDF.")
                raise ValueError("Uploaded file is not a PDF.")
            else:
                # --- 5. Save Uploaded File Temporarily ---
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_f:
                        temp_f.write(uploaded_content)
                        temp_upload_path = temp_f.name
                    logging.info(f"Uploaded file '{uploaded_filename}' ({len(uploaded_content)} bytes) saved temporarily to: {temp_upload_path}")
                    logging.info("Proceed to the next cell to process the file.")
                except Exception as save_e:
                     logging.error(f"Failed to save uploaded file temporarily: {save_e}")
                     temp_upload_path = None # Ensure path is None if save failed
                     raise RuntimeError("Failed to save temporary file.") from save_e
        else: # uploaded is empty dict
             logging.warning("No file was selected during upload.")
             # No need to raise error, just won't proceed
    else:
         logging.warning("File upload process did not return any files (cancelled or failed).")


# CELL 10: Process Uploaded File and Cleanup
# This cell "calls" the code from all of the previous cells where we set the project up.


# Cell 10: Process Uploaded File and Cleanup
if __name__ == "__main__":
    # Check if upload was successful and we have the path
    if 'temp_upload_path' not in locals() or not temp_upload_path or not os.path.exists(temp_upload_path):
         logging.error("Temporary upload path not found or file doesn't exist. Please run the upload cell successfully first.")
         # Don't raise error here, just skip processing if upload failed cleanly
    elif 'client' not in locals() or not client or not gs_path or not pdftk_path:
         logging.error("Setup variables not found. Please ensure Cell 8 ran successfully.")
         # Don't raise error here, just skip processing
    else:
        # Proceed with processing
        processing_successful = False # Flag to track outcome
        try:
            # --- 6. Call the Handler Function ---
            # Use uploaded_filename from the previous cell if you need it for logging
            # If not, os.path.basename(temp_upload_path) will be the temp name
            logging.info(f"--- Calling processing handler for temporary file: {temp_upload_path} ---")
            processing_start_time = time.time()

            final_output_file_path = handle_uploaded_pdf(
                uploaded_pdf_path=temp_upload_path,
                config=config,
                gs_path=gs_path,
                pdftk_path=pdftk_path,
                client=client
            )

            processing_end_time = time.time()
            processing_duration = processing_end_time - processing_start_time
            logging.info(f"--- Processing handler finished in {processing_duration:.2f} seconds ---")

            # --- 7. Report Final Status ---
            if final_output_file_path:
                logging.info(f"=== Processing SUCCEEDED ===")
                logging.info(f"Final bookmarked file saved to: {final_output_file_path}")
                processing_successful = True
            else:
                logging.error(f"=== Processing FAILED ===")
                logging.error("Check logs above for specific error details.")

        except Exception as process_e:
             logging.critical(f"An unexpected critical error occurred during processing: {process_e}", exc_info=True)

        finally:
            # --- 8. Cleanup ---
            logging.info("--- Initiating final cleanup ---")
            if temp_upload_path and os.path.exists(temp_upload_path):
                try:
                    os.remove(temp_upload_path)
                    logging.info(f"Cleaned up temporary upload file: {temp_upload_path}")
                except OSError as e:
                    logging.error(f"Failed to clean up temporary upload file {temp_upload_path}: {e}")
            else:
                 logging.info("No temporary upload file path found or file already deleted.")

    logging.info("=== Main Execution Block Finished ===")