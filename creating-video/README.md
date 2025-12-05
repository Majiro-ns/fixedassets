# Creating Video Project

This project is a skeleton for a local-only, API-free video generation pipeline. It provides the basic structure for configuration, scripting, and testing.

**Note:** The current version only produces dummy (solid-color) videos. The core logic in `scripts/generate_video.py` is designed to be replaced with a real Stable Diffusion or SVD pipeline later.

## Setup

1.  **Create a virtual environment:**
    ```bash
    python -m venv .venv
    ```

2.  **Activate the environment:**
    - On Windows:
      ```powershell
      .\.venv\Scripts\Activate.ps1
      ```
    - On macOS/Linux:
      ```bash
      source .venv/bin/activate
      ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## How to Run

You can run the video generation from the command line.

-   **Using Python directly:**
    ```bash
    python scripts/generate_video.py --config configs/default.yaml
    ```

-   **Using the PowerShell script (on Windows):**
    ```powershell
    .\run_video.ps1
    ```

Generated videos will appear in the `outputs/videos` directory, and corresponding logs in `outputs/logs`.

## How to Run Tests

To ensure the pipeline is working correctly, you can run the smoke test using pytest.

```bash
python -m pytest tests/test_smoke.py -q
```

This will run a quick test that generates a very short, small-resolution video and confirms its existence.

