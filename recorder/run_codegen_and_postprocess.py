import subprocess

import sys

# ----------------------------------------------------------

# Hardcoded arguments (edit as needed)

# ----------------------------------------------------------

CODEGEN_PATH = 'recorder/launch_codegen.py'

POSTPROCESS_PATH = 'recorder/postprocess_codegen.py'

# URL to launch Playwright codegen

CODEGEN_URL = 'https://demoqa.com/'  # <-- change as needed

# Scenario name passed to postprocess

POSTPROCESS_SCENARIO = 'Checking Agentic AI '  # <-- change as needed

# Shared codegen output file

CODEGEN_OUTPUT_FILE = 'codegen_output.py'  # <-- change as needed


def run_script(script_path, args=None):

    cmd = [sys.executable, script_path]

    if args:

        cmd.extend(args)

    print(f"Running: {' '.join(cmd)}")

    result = subprocess.run(

        cmd,

        capture_output=True,

        text=True

    )

    # Print stdout

    if result.stdout:

        print(result.stdout)

    # Print stderr if any

    if result.stderr:

        print("Errors:")

        print(result.stderr)

    # Fail fast on error

    if result.returncode != 0:

        print(f"{script_path} failed with exit code {result.returncode}")

        sys.exit(result.returncode)


def main():

    # ------------------------------------------------------

    # 1. Launch Playwright codegen

    # ------------------------------------------------------

    codegen_args = [

        '--url', CODEGEN_URL,

        '--output', CODEGEN_OUTPUT_FILE

    ]

    run_script(CODEGEN_PATH, codegen_args)

    # ------------------------------------------------------

    # 2. Run postprocess on generated code

    # ------------------------------------------------------

    postprocess_args = [

        '--codegen', CODEGEN_OUTPUT_FILE,

        '--scenario', POSTPROCESS_SCENARIO

    ]

    run_script(POSTPROCESS_PATH, postprocess_args)

    print("Both codegen and postprocess completed successfully.")


if __name__ == '__main__':

    main()
 