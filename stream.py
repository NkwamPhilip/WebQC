import streamlit as st
import zipfile
import uuid
import shutil
import subprocess
import requests
from pathlib import Path
import os
import json
import datetime

# ------------------------------
# Streamlit Page Configuration & Branding
# ------------------------------
st.set_page_config(page_title="MRIQC App", layout="wide")


st.markdown("""
# Medical Artificial Intelligence Lab  
### MRIQC Web App for Scientific MRI Data Quality Assessment

This tool converts DICOM MRI data into BIDS format and runs MRI Quality Control to generate quality reports.  
It includes:
- DICOM → BIDS conversion,
- Sending the BIDS dataset to a server,
- Running MRIQC with real-time log streaming,
- And downloading the final results.
""", unsafe_allow_html=True)

with st.expander("🧠 MRIQC Image Quality Metrics (IQMs) – Full Descriptions"):
    st.markdown("""
## 🧠 Anatomical (T1w / T2w) IQMs

**1. CNR – Contrast-to-Noise Ratio**  
Measures how well different tissues (like gray matter and white matter) are distinguished.  
🟢 Higher CNR = better tissue contrast.

**2. SNR – Signal-to-Noise Ratio**  
Assesses the strength of the signal relative to background noise.  
🟢 Higher SNR = cleaner images.

**3. EFC – Entropy Focus Criterion**  
Quantifies image sharpness using Shannon entropy.  
🔴 Higher EFC = more ghosting or blurring (i.e., less sharp).

**4. FBER – Foreground-Background Energy Ratio**  
Compares energy inside the brain mask vs outside.  
🟢 Higher FBER = better tissue delineation.

**5. FWHM – Full Width at Half Maximum**  
Estimates smoothness in spatial resolution.  
🟡 Lower FWHM = sharper images, but depends on scanner/protocol.

**6. INU – Intensity Non-Uniformity**  
Evaluates bias fields caused by scanner imperfections.  
🔴 Higher INU = more uneven signal across image.

**7. QI1 – Quality Index 1**  
Measures artifacts in areas outside the brain.  
🔴 Higher QI1 = more artifacts (e.g., motion, ghosting).

**8. QI2 – Quality Index 2**  
Detects structured noise using chi-squared goodness-of-fit.  
🔴 Higher QI2 = likely issues with signal consistency.

**9. WM2MAX – White Matter to Max Intensity Ratio**  
Checks if white matter intensity is in a normal range.  
🟡 Very high or low values may indicate poor normalization or acquisition problems.

---

## 🧠 Functional (BOLD / fMRI) IQMs

**1. FD – Framewise Displacement**  
Quantifies subject head movement across volumes.  
🔴 Higher FD = more motion artifacts.  
🟢 Mean FD < 0.2mm is often acceptable.

**2. DVARS – D Temporal Variance of Signal**  
Measures signal change between consecutive volumes.  
🔴 Spikes in DVARS = potential motion or noise events.

**3. tSNR – Temporal Signal-to-Noise Ratio**  
SNR over time (mean / std of time series per voxel).  
🟢 Higher tSNR = more reliable signal over time.

**4. GCOR – Global Correlation**  
Detects global signal fluctuations across the brain.  
🔴 High GCOR may indicate widespread noise.

**5. AOR – AFNI Outlier Ratio**  
Counts the number of voxels flagged as statistical outliers.  
🔴 High AOR = poor scan quality or motion-related issues.

**6. GSR – Global Signal Regression Impact**  
Assesses how removing global signal changes BOLD contrast.  
🟡 Large differences might affect downstream results.

---

🔎 **For deeper technical explanations and formulas, see the [MRIQC Documentation](https://mriqc.readthedocs.io/en/stable/iqms/iqms.html).**
""")


# ------------------------------
# Default AWS Server Settings (Hidden)
# ------------------------------
DEFAULT_API_URL = "http://51.21.190.32:8000"
DEFAULT_WS_URL = "ws://51.21.190.32:8000/ws/mriqc"

# ------------------------------
# Helper Functions
# ------------------------------


def generate_dcm2bids_config(temp_dir: Path) -> Path:
    config = {
        "descriptions": [
            {
                "dataType": "anat",
                "modalityLabel": "T1w",
                "criteria": {"SeriesDescription": "(?i).*t1.*"},
                "sidecarChanges": {"ProtocolName": "T1w"}
            },
            {
                "dataType": "anat",
                "modalityLabel": "T2w",
                "criteria": {"SeriesDescription": "(?i).*t2.*"},
                "sidecarChanges": {"ProtocolName": "T2w"}
            },
            {
                "dataType": "anat",
                "modalityLabel": "FLAIR",
                "criteria": {"SeriesDescription": "(?i).*flair.*"},
                "sidecarChanges": {"ProtocolName": "FLAIR"}
            },
            {
                "dataType": "dwi",
                "modalityLabel": "dwi",
                "criteria": {"SeriesDescription": "(?i).*dwi.*|.*dti.*"},
                "sidecarChanges": {"ProtocolName": "DWI"}
            },
            {
                "dataType": "func",
                "modalityLabel": "bold",
                "criteria": {"SeriesDescription": "(?i).*bold.*|.*fmri.*"},
                "sidecarChanges": {"ProtocolName": "BOLD"}
            }
        ]
    }
    config_file = temp_dir / "dcm2bids_config.json"
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=4)
    return config_file


def run_dcm2bids(dicom_dir: Path, bids_out: Path, subj_id: str, ses_id: str, config_file: Path):
    cmd = ["dcm2bids", "-d", str(dicom_dir), "-p", subj_id,
           "-c", str(config_file), "-o", str(bids_out)]
    if ses_id:
        cmd += ["-s", ses_id]
    st.write(f"**Running**: `{' '.join(cmd)}`")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        st.error(f"dcm2bids error:\n{result.stderr}")
    else:
        st.success("dcm2bids completed successfully.")
        st.text(result.stdout)


def move_files_in_tmp(bids_out: Path, subj_id: str, ses_id: str):
    tmp_folder = bids_out / "tmp_dcm2bids" / f"sub-{subj_id}_ses-{ses_id}"
    if not tmp_folder.exists():
        return
    sub_dir = bids_out / f"sub-{subj_id}"
    ses_dir = sub_dir / f"ses-{ses_id}" if ses_id else sub_dir
    ses_dir.mkdir(parents=True, exist_ok=True)
    modality_paths = {
        "anat": ses_dir / "anat",
        "dwi": ses_dir / "dwi",
        "func": ses_dir / "func"
    }
    for fpath in tmp_folder.rglob("*"):
        if not fpath.is_file():
            continue
        exts = "".join(fpath.suffixes)
        if not any(exts.endswith(e) for e in [".nii", ".nii.gz", ".json", ".bval", ".bvec"]):
            continue
        fname = fpath.name.lower()
        if "t1" in fname:
            modality_label = "anat"
            suffix = "T1w"
        elif "t2" in fname:
            modality_label = "anat"
            suffix = "T2w"
        elif "flair" in fname:
            modality_label = "anat"
            suffix = "FLAIR"
        elif "dwi" in fname or "dti" in fname:
            modality_label = "dwi"
            suffix = "dwi"
        elif "bold" in fname or "fmri" in fname:
            modality_label = "func"
            suffix = "bold"
        else:
            continue
        target_dir = modality_paths[modality_label]
        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)
        new_basename = f"sub-{subj_id}"
        if ses_id:
            new_basename += f"_ses-{ses_id}"
        new_basename += f"_{suffix}{exts}"
        new_path = target_dir / new_basename
        fpath.rename(new_path)
    shutil.rmtree(tmp_folder.parent, ignore_errors=True)
    st.info("Cleaned up leftover files in tmp_dcm2bids.")


def create_bids_top_level_files(bids_dir: Path, subject_id: str):
    dd_file = bids_dir / "dataset_description.json"
    if not dd_file.exists():
        dataset_description = {
            "Name": "Example dataset",
            "BIDSVersion": "1.6.0",
            "License": "CC0",
            "Authors": ["Philip Nkwam", "Udunna Anazodo", "Maruf Adewole", "Sekinat Aderibigbe"],
            "DatasetType": "raw"
        }
        with open(dd_file, 'w') as f:
            json.dump(dataset_description, f, indent=4)
    readme_file = bids_dir / "README"
    if not readme_file.exists():
        content = f"""\
# BIDS Dataset

This dataset was automatically generated by dcm2bids.

**Contents**:
- Anat: T1w, T2w, FLAIR
- DWI: Diffusion Weighted Imaging
- Func: BOLD/fMRI scans

Please see the official [BIDS documentation](https://bids.neuroimaging.io) for details.
"""
        with open(readme_file, 'w') as f:
            f.write(content)
    changes_file = bids_dir / "CHANGES"
    if not changes_file.exists():
        content = f"1.0.0 {datetime.datetime.now().strftime('%Y-%m-%d')}\n  - Initial BIDS conversion\n"
        with open(changes_file, 'w') as f:
            f.write(content)
    participants_tsv = bids_dir / "participants.tsv"
    if not participants_tsv.exists():
        with open(participants_tsv, 'w') as f:
            f.write("participant_id\tage\tsex\n")
            f.write(f"sub-{subject_id}\tN/A\tN/A\n")
    participants_json = bids_dir / "participants.json"
    if not participants_json.exists():
        pjson = {
            "participant_id": {"Description": "Unique ID"},
            "age": {"Description": "Age in years"},
            "sex": {"Description": "Biological sex"}
        }
        with open(participants_json, 'w') as f:
            json.dump(pjson, f, indent=4)


def zip_directory(folder_path: Path, zip_file_path: Path):
    shutil.make_archive(str(zip_file_path.with_suffix("")),
                        "zip", root_dir=folder_path)

# ------------------------------
# Real-Time WebSocket Log Viewer
# ------------------------------


def websocket_log_viewer(ws_url: str):
    html_code = f"""
    <html>
      <head>
        <style>
          body {{
            font-family: Arial, sans-serif;
          }}
          #log {{
            width: 100%;
            height: 600px;
            border: 1px solid #ccc;
            overflow-y: scroll;
            white-space: pre-wrap;
            background-color: #f9f9f9;
            padding: 10px;
          }}
        </style>
      </head>
      <body>
        <h3>MRIQC Real-Time Log</h3>
        <div id="log">Connecting to {ws_url}...</div>
        <script>
          var logDiv = document.getElementById("log");
          var ws = new WebSocket("{ws_url}");
          ws.onopen = function() {{
              logDiv.innerHTML += "\\nWebSocket connection established.";
          }};
          ws.onmessage = function(event) {{
              logDiv.innerHTML += "\\n" + event.data;
              logDiv.scrollTop = logDiv.scrollHeight;
          }};
          ws.onclose = function() {{
              logDiv.innerHTML += "\\nWebSocket connection closed.";
          }};
          ws.onerror = function(error) {{
              logDiv.innerHTML += "\\nWebSocket error: " + error;
          }};
        </script>
      </body>
    </html>
    """
    st.components.v1.html(html_code, height=700)

# ------------------------------
# Main Streamlit App
# ------------------------------


def main():
    st.title("DICOM → BIDS → MRI Quality Control")

    # Input: Subject and Session
    subj_id = st.text_input("Subject ID (e.g. '01')", value="01")
    ses_id = st.text_input("Session ID (optional)", value="Baseline")

    # Multi-select for modalities
    selected_modalities = st.multiselect(
        "Select MRIQC modalities:",
        ["T1w", "T2w", "bold"],
        default=["T1w"]
    )
    modalities_str = " ".join(selected_modalities)

    # Set AWS endpoints (hidden from the user)
    aws_api_url = "http://51.21.190.32:8000"
    ws_url = "ws://51.21.190.32:8000/ws/mriqc"

    dicom_zip = st.file_uploader("Upload DICOM ZIP", type=["zip"])

    if dicom_zip:
        # Phase 1: DICOM to BIDS Conversion
        if st.button("Run DICOM → BIDS Conversion"):
            with st.spinner("Converting DICOM to BIDS..."):
                job_id = str(uuid.uuid4())[:8]
                temp_dir = Path(f"temp_{job_id}")
                temp_dir.mkdir(exist_ok=True)

                dicom_dir = temp_dir / "dicoms"
                dicom_dir.mkdir(exist_ok=True)
                with zipfile.ZipFile(dicom_zip, 'r') as zf:
                    zf.extractall(dicom_dir)
                st.success(f"DICOMs extracted to {dicom_dir}")

                bids_out = temp_dir / "bids_output"
                bids_out.mkdir(exist_ok=True)

                config_file = generate_dcm2bids_config(temp_dir)
                run_dcm2bids(dicom_dir, bids_out, subj_id, ses_id, config_file)

                move_files_in_tmp(bids_out, subj_id, ses_id)
                create_bids_top_level_files(bids_out, subj_id)

                ds_file = bids_out / "dataset_description.json"
                if ds_file.exists():
                    st.success(
                        "dataset_description.json created successfully.")
                else:
                    st.error("dataset_description.json not found at BIDS root!")

                bids_zip_path = temp_dir / "bids_dataset.zip"
                zip_directory(bids_out, bids_zip_path)
                st.success("DICOM to BIDS conversion complete!")
                st.info(f"BIDS dataset is ready: {bids_zip_path}")

                with open(bids_zip_path, "rb") as f:
                    st.download_button("Download BIDS Dataset", data=f,
                                       file_name="BIDS_dataset.zip", mime="application/zip")

                st.session_state.temp_dir = str(temp_dir)

        # Phase 2: Send BIDS to AWS for MRIQC Processing
        if st.button("Send BIDS for MRIQC"):
            if "temp_dir" not in st.session_state:
                st.error("No BIDS dataset found. Please run the conversion first.")
                return
            else:
                temp_dir = Path(st.session_state.temp_dir)

            bids_zip_path = temp_dir / "bids_dataset.zip"
            files = {
                "bids_zip": ("bids_dataset.zip", open(bids_zip_path, "rb"), "application/zip")
            }
            data = {
                "participant_label": subj_id,
                "modalities": modalities_str
            }
            api_endpoint = f"{aws_api_url}/run-mriqc"
            st.write(
                f"Sending BIDS + modalities={modalities_str} to {api_endpoint} ...")

            response = requests.post(api_endpoint, files=files, data=data)
            if response.status_code != 200:
                st.error(f"MRIQC failed: {response.text}")
                return

            # Save MRIQC results ZIP file
            result_zip = temp_dir / "mriqc_results.zip"
            with open(result_zip, "wb") as f:
                f.write(response.content)
            st.success("MRIQC results received from server!")

            # Offer a download button for MRIQC results ZIP
            with open(result_zip, "rb") as f:
                st.download_button("Download MRIQC Results", data=f,
                                   file_name="mriqc_results.zip", mime="application/zip")

            result_dir = temp_dir / "mriqc_results"
            result_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(result_zip, 'r') as zf:
                zf.extractall(result_dir)
            st.info(f"Results unzipped in {result_dir}")

            log_files = list(result_dir.rglob("mriqc_log.txt"))
            if log_files:
                with open(log_files[0], "r") as lf:
                    log_data = lf.read()
                st.subheader("MRIQC Log")
                st.text_area("Log Output", log_data, height=400)
            else:
                st.warning("No MRIQC log file found.")

            html_reports = list(result_dir.rglob("*.html"))
            if not html_reports:
                st.warning("No HTML reports found in MRIQC results.")
            else:
                for report in html_reports:
                    st.write(f"Report found: {report}")
                    with open(report, "r") as rf:
                        html_data = rf.read()
                    st.components.v1.html(
                        html_data, height=1000, scrolling=True)

            st.success("MRIQC processing complete!")


# Display a lab logo and app description.
LOGO_PATH = "MLAB.png"  # Replace with your local file or URL for your lab's logo
try:
    st.image(LOGO_PATH, width=200)
except Exception:
    st.warning("Logo not found. Please update the LOGO_PATH variable.")

st.markdown("""
# Medical Artificial Intelligence Lab """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
