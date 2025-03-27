from pydicom import dcmread
import re
import pandas as pd
from bs4 import BeautifulSoup
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
import numpy as np
import nibabel as nib
from pydicom import dcmread  # For validation

# ------------------------------
# Streamlit Page Configuration & Branding
# ------------------------------
st.set_page_config(page_title="MRIQC App", layout="wide")

st.markdown("""
# MRIQC Web App for MRI Image Quality Assessment

The WebQC App provides an intuitive web interface for running Quality Control on MRI datasets acquired in DICOM formats. The App offers users the ability to compute Image Quality Metrics (IQMs) for neuroimaging studies.
This web-based solution implements the original MRIQC standalone application in a user-friendly interface accessible from any device, without the need for software installation or access to resource-intensive computers. Thus, simplifying the quality control workflow. For a comprehensive understanding of the IQMs computed by MRIQC, as well as details on the original MRIQC implementation, refer to the official MRIQC documentation: https://mriqc.readthedocs.io.
""",
            unsafe_allow_html=True
            )

st.markdown(
    """
## How to Use:
The app enables users to upload T1w, T2w, or BOLD fMRI DICOM files as a folder or zipped format, convert them to the Standard Brain Imaging Data Structure (BIDS) format using dcm2bids [1] via dcm2niiX [2], and then process the IQMs using MRIQC [3]. The resulting reports can be downloaded for further analysis. To use, follow the following steps:

1. Enter Subject ID (optional)
2. Enter the Session ID (optional, e.g, baseline, follow up, etc)
3. Select your preferred modality for analysis (T1w, T2w, DWI, or BOLD fMRI)
4. Upload a zipped file/folder containing T1w, T2w, DWI, or BOLD fMRI DICOM images by dragging and dropping the zipped file or uploading using the browse file option
5. Click DICOM → BIDS Conversion
6. Once BIDS converted, you will see the notification: DICOM to BIDS conversion complete
7. Click Send BIDS to Web for MRIQC or if you want the BIDS format, Click Download BIDS Dataset to your device.
8. Send the converted BIDS images to MRIQC by clicking Send BIDS to Web for MRIQC  for generating the IQMs
9. Depending on your internet connection, this can between 5-10 minutes to get your results for a single participant.
10. When completed, you can view the report on the web App or download the report of the IQM by clicking the “Download MRIQC results” button including the csv export.




## References
1. Boré, A., Guay, S., Bedetti, C., Meisler, S., & GuenTher, N. (2023). Dcm2Bids (Version 3.1.1) [Computer software]. https://doi.org/10.5281/zenodo.8436509
2. Li X, Morgan PS, Ashburner J, Smith J, Rorden C. The first step for neuroimaging data analysis: DICOM to NIfTI conversion. J Neurosci Methods., 2016, 264:47-56.
3. Esteban O, Birman D, Schaer M, Koyejo OO, Poldrack RA, Gorgolewski KJ (2017) MRIQC: Advancing the automatic prediction of image quality in MRI from unseen sites. PLoS ONE 12(9): e0184661. https://doi.org/10.1371/journal.pone.0184661

""", unsafe_allow_html=True)


# Display IQM tables in Markdown
st.markdown("""
### **Anatomical (T1w / T2w) IQMs**

| Abbreviation | Name                                 | Description                                                                                                                                    |
|--------------|--------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| **CNR**      | Contrast-to-Noise Ratio              | Measures how well different tissues (like gray matter and white matter) are distinguished. Higher CNR indicates better tissue contrast.        |
| **SNR**      | Signal-to-Noise Ratio                | Assesses the strength of the signal relative to background noise. Higher SNR means clearer images.                                             |
| **EFC**      | Entropy Focus Criterion              | Quantifies image sharpness using Shannon entropy. Higher EFC indicates more ghosting/blurring (i.e., less sharp).                              |
| **FBER**     | Foreground-Background Energy Ratio   | Compares energy inside the brain mask vs outside. Higher FBER reflects better tissue delineation.                                              |
| **FWHM**     | Full Width at Half Maximum           | Estimates the smoothness in spatial resolution. Lower FWHM typically implies sharper images (depends on scanner/protocol).                     |
| **INU**      | Intensity Non-Uniformity             | Evaluates bias fields caused by scanner imperfections. Higher INU suggests more uneven signal across the image.                                |
| **Art_QI1**  | Quality Index 1                      | Measures artifacts in areas outside the brain. Higher QI1 = more artifacts (e.g., motion, ghosting).                                           |
| **Art_QI2**  | Quality Index 2                      | Detects structured noise using a chi-squared goodness-of-fit test. Higher QI2 indicates potential issues with signal consistency.              |
| **WM2MAX**   | White Matter to Max Intensity Ratio  | Checks if white matter intensity is within a normal range. Very high or low values may indicate problems with normalization or acquisition.    |

### **Functional (BOLD MRI) IQMs**

| Abbreviation | Name                               | Description                                                                                                                    |
|--------------|------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| **FD**       | Framewise Displacement             | Quantifies subject head movement across volumes. Higher FD = more motion artifacts. Mean FD < 0.2 mm is often acceptable.     |
| **DVARS**    | D Temporal Variance of Signal      | Measures the change in signal between consecutive volumes. Spikes in DVARS can indicate motion or noise events.               |
| **tSNR**     | Temporal Signal-to-Noise Ratio     | Assesses the SNR over time (mean / std of the time series per voxel). Higher tSNR = more reliable signal over time.           |
| **GCOR**     | Global Correlation                 | Detects global signal fluctuations across the brain. Elevated GCOR may reflect widespread noise.                              |
| **AOR**      | AFNI Outlier Ratio                 | Counts the number of voxels flagged as statistical outliers. High AOR suggests poor scan quality or significant motion issues. |
| **GSR**      | Global Signal Regression Impact    | Assesses how removing global signal changes BOLD contrast. Large differences might affect downstream analysis.                |

*For deeper technical explanations, see the [MRIQC Documentation](https://mriqc.readthedocs.io/en/latest/iqms/iqms.html).*
""")

# ... continue your Streamlit code (other steps, logic, etc.) ...


# ------------------------------
# Default AWS Server Settings (Hidden)
# ------------------------------
aws_api_url = "http://51.21.190.32:8000"
ws_url = "ws://51.21.190.32:8000/ws/mriqc"

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
                "criteria": {"SeriesDescription": "(?i).*flair.*|.*fluid.*"},
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
                "criteria": {"SeriesDescription": "(?i).*bold.*|.*fmri.*|.*FMRI.*|.*run.*|.*fMRI.*"},
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
        # st.text(result.stdout)


# ------------------------------
# Streamlit Page Configuration & Branding
# ------------------------------

st.markdown("""
# MRIQC Web App for MRI Image Quality Assessment
[Rest of your header content remains exactly the same...]
""", unsafe_allow_html=True)

# ------------------------------
# Helper Functions (Updated)
# ------------------------------


def organize_dicom_conversion(bids_out: Path, subj_id: str, ses_id: str):
    """Improved DICOM series handling that reliably selects largest files by size"""
    tmp_folder = bids_out / "tmp_dcm2bids"

    if not tmp_folder.exists():
        st.warning(f"Temporary conversion folder not found: {tmp_folder}")
        return

    # 1. First collect ALL files and their sizes
    all_files = []
    for fpath in tmp_folder.rglob('*'):
        if fpath.is_file() and fpath.suffix.lower() in ['.nii', '.gz', '.json', '.bval', '.bvec']:
            all_files.append({
                'path': fpath,
                'size': fpath.stat().st_size,  # Actual file size in bytes
                'stem': fpath.stem  # Base filename without extension
            })

    # 2. Group files by their base filename stem (before extensions)
    file_groups = {}
    for file in all_files:
        file_groups.setdefault(file['stem'], []).append(file)

    # 3. Process each group to find largest NIfTI
    for stem, files in file_groups.items():
        # Get all NIfTI files in this group (.nii or .nii.gz)
        niftis = [f for f in files if f['path'].suffix.lower() in [
            '.nii', '.gz']]

        if not niftis:
            continue  # Skip groups without NIfTI files

        # Select the single largest NIfTI file by size
        largest_nifti = max(niftis, key=lambda x: x['size'])

        # Get all associated files (same stem but different extensions)
        associated_files = [
            f for f in files if f['path'] != largest_nifti['path']]

        # 4. Determine modality from filename patterns
        fname = largest_nifti['path'].name.lower()
        if 't1' in fname:
            modality = 'anat'
            suffix = 'T1w'
        elif 't2' in fname:
            modality = 'anat'
            suffix = 'T2w'
        elif any(x in fname for x in ['flair', 'fluid']):
            modality = 'anat'
            suffix = 'FLAIR'
        elif any(x in fname for x in ['dwi', 'dti']):
            modality = 'dwi'
            suffix = 'dwi'
        elif any(x in fname for x in ['bold', 'fmri', 'func', 'task']):
            modality = 'func'
            suffix = 'bold'
        else:
            # Fallback to checking JSON sidecar if exists
            json_file = next(
                (f for f in associated_files if f['path'].suffix.lower() == '.json'), None)
            if json_file:
                try:
                    with open(json_file['path'], 'r') as f:
                        metadata = json.load(f)
                    if 'SeriesDescription' in metadata:
                        desc = metadata['SeriesDescription'].lower()
                        if 't1' in desc:
                            modality = 'anat'
                            suffix = 'T1w'
                        elif 't2' in desc:
                            modality = 'anat'
                            suffix = 'T2w'
                        elif any(x in desc for x in ['dwi', 'diffusion']):
                            modality = 'dwi'
                            suffix = 'dwi'
                        elif any(x in desc for x in ['bold', 'fmri']):
                            modality = 'func'
                            suffix = 'bold'
                except:
                    pass

        # 5. Move files to BIDS structure
        bids_name = f"sub-{subj_id}"
        if ses_id:
            bids_name += f"_ses-{ses_id}"

        if modality == 'func':
            task_name = 'rest'  # Default if not found
            # Try to extract from filename
            task_match = re.search(r'task-([a-zA-Z0-9]+)', fname)
            if task_match:
                task_name = task_match.group(1)
            bids_name += f"_task-{task_name}"

        bids_name += f"_{suffix}{largest_nifti['path'].suffix}"

        # Create target directory
        target_dir = bids_out / f"sub-{subj_id}"
        if ses_id:
            target_dir = target_dir / f"ses-{ses_id}"
        target_dir = target_dir / modality
        target_dir.mkdir(parents=True, exist_ok=True)

        # Move main NIfTI file
        new_path = target_dir / bids_name
        largest_nifti['path'].rename(new_path)
        st.info(
            f"Moved {largest_nifti['path'].name} (Size: {largest_nifti['size']/1024/1024:.1f} MB)")

        # Move associated files
        for assoc in associated_files:
            if assoc['path'].suffix.lower() == '.json':
                assoc_path = new_path.with_suffix('.json')
            elif assoc['path'].suffix.lower() == '.bval':
                assoc_path = new_path.with_suffix('.bval')
            elif assoc['path'].suffix.lower() == '.bvec':
                assoc_path = new_path.with_suffix('.bvec')
            else:
                continue

            assoc['path'].rename(assoc_path)
            st.info(f"└─ Moved associated: {assoc['path'].name}")

    # Cleanup
    shutil.rmtree(tmp_folder, ignore_errors=True)
    st.success("BIDS organization complete - removed temporary files")


def validate_dicom_series(dicom_dir: Path):
    """Quick validation of DICOM consistency"""
    from pydicom import dcmread
    series = {}
    for dcm_file in dicom_dir.rglob('*'):
        try:
            ds = dcmread(str(dcm_file), stop_before_pixels=True)
            key = (ds.SeriesInstanceUID, ds.SeriesNumber)
            series.setdefault(key, []).append(dcm_file)
        except:
            continue
    return series


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
# Web Scraper
# ------------------------------


def extract_iqms_from_html(html_file: Path):
    iqms = {}
    with open(html_file, 'r', encoding='utf-8') as file:
        soup = BeautifulSoup(file, 'html.parser')

    iqm_table = soup.find("table", {"id": "iqms-table"})
    if iqm_table:
        rows = iqm_table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) == 2:
                metric_name = cols[0].get_text(strip=True)
                metric_value = cols[1].get_text(strip=True)
                iqms[metric_name] = metric_value

    return iqms


def extract_all_iqms(result_dir: Path):
    iqm_list = []
    html_reports = list(result_dir.rglob("*.html"))
    for html_file in html_reports:
        iqms = extract_iqms_from_html(html_file)
        iqms["Report Filename"] = html_file.name
        iqm_list.append(iqms)
    return pd.DataFrame(iqm_list)


# ------------------------------
# Main Streamlit App
# ------------------------------


def main():
    st.title("DICOM → BIDS → MRIQC")

    subj_id = st.text_input("Subject ID (e.g. '01')", value="01")
    ses_id = st.text_input("Session ID (optional)", value="Baseline")

    selected_modalities = st.multiselect(
        "Select MRIQC modalities:",
        ["T1w", "T2w", "bold", "flair", "dwi"],
        default=["T1w"]
    )
    modalities_str = " ".join(selected_modalities)

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

                organize_dicom_conversion(bids_out, subj_id, ses_id)
                # After DICOM extraction
                dicom_series = validate_dicom_series(dicom_dir)
                st.info(f"Found {len(dicom_series)} DICOM series")
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
        if st.button("Send BIDS to Web for MRIQC"):
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
            st.write(f"Sending BIDS + modalities={modalities_str} to web ...")

            response = requests.post(api_endpoint, files=files, data=data)
            if response.status_code != 200:
                st.error(f"MRIQC failed: {response.text}")
                return

            # Save the MRIQC results ZIP file received from server
            result_zip = temp_dir / "mriqc_results.zip"
            with open(result_zip, "wb") as f:
                f.write(response.content)
            st.success("MRIQC results received from server!")

            # Extract the MRIQC results
            result_dir = temp_dir / "mriqc_results"
            result_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(result_zip, 'r') as zf:
                zf.extractall(result_dir)

            # --- Automatically Extract IQMs from HTML Reports ---
            def extract_iqms_from_html(html_file: Path):
                iqms = {}
                with open(html_file, 'r', encoding='utf-8') as file:
                    soup = BeautifulSoup(file, 'html.parser')

                iqm_table = soup.find("table", {"id": "iqms-table"})
                if iqm_table:
                    rows = iqm_table.find_all("tr")
                    for row in rows:
                        cols = row.find_all("td")
                        if len(cols) == 2:
                            metric_name = cols[0].text.strip()
                            metric_value = cols[1].text.strip()
                            iqms[metric_name] = metric_value
                return iqms

            iqm_records = []
            html_reports = list(result_dir.rglob("*.html"))

            if html_reports:
                for html_file in html_reports:
                    iqms = extract_iqms_from_html(html_file)
                    iqms['Report Filename'] = html_file.name
                    iqm_records.append(iqms)

                iqms_df = pd.DataFrame(iqm_records)

                # Save IQMs CSV directly into results directory
                iqm_csv_path = result_dir / "MRIQC_IQMs.csv"
                iqms_df.to_csv(iqm_csv_path, index=False)
                st.success("IQMs extracted successfully from HTML reports!")

                # Re-zip results folder including IQMs CSV
                updated_zip_path = temp_dir / "mriqc_results_with_IQMs"
                shutil.make_archive(str(updated_zip_path),
                                    'zip', root_dir=result_dir)

                # Single download button for complete package
                with open(f"{updated_zip_path}.zip", "rb") as f:
                    st.download_button(
                        "Download MRIQC Results (including IQMs CSV)",
                        data=f,
                        file_name="mriqc_results_with_IQMs.zip",
                        mime="application/zip"
                    )

                # Optionally display IQMs dataframe in the app
                st.subheader("Extracted Image Quality Metrics (IQMs)")
                st.dataframe(iqms_df)

            else:
                st.warning(
                    "No HTML reports found in MRIQC results for IQM extraction.")

            # Display MRIQC log if exists
            log_files = list(result_dir.rglob("mriqc_log.txt"))
            if log_files:
                with open(log_files[0], "r") as lf:
                    log_data = lf.read()
                st.subheader("MRIQC Log")
                st.text_area("Log Output", log_data, height=400)
            else:
                st.warning("No MRIQC log file found.")

            # Display HTML reports inline in Streamlit
            for report in html_reports:
                with open(report, "r") as rf:
                    html_data = rf.read()
                st.components.v1.html(html_data, height=1000, scrolling=True)

            st.success("MRIQC processing and IQM extraction complete!")


if __name__ == "__main__":
    main()

# ------------------------------
# Footer: Lab Branding (Custom)
# ------------------------------

st.markdown(
    """
   <div style="text-align: center; margin-top: 50px;">
       <img src="https://github.com/NkwamPhilip/MLAB/blob/2545d5774dc9b376b6b0180f25388bace232497c/MLAB.png" alt="Lab Logo" style="height: 50px;">
       <h3>Medical Artificial Intelligence Lab</h3>
   </div>
   """,
    unsafe_allow_html=True
)


# Container with collective padding
st.markdown("""
    <div style="padding: 100px;">
""", unsafe_allow_html=True)

# Adjust column widths to center contents
col1, col2 = st.columns([1, 3])

with col1:
    st.image("MLAB.png", width=250)

with col2:
    st.markdown(
        "<h2 style='padding-top: 40px;'>Medical Artificial Intelligence Lab</h2>",
        unsafe_allow_html=True
    )

# Close container div
st.markdown("</div>", unsafe_allow_html=True)


st.markdown(
    """
    <style>
    /* Hide Streamlit's default footer */
    footer { visibility: hidden; }
    /* Custom footer styling */
    .custom-footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: #f9f9f9;
        text-align: center;
        padding: 10px 0;
        border-top: 1px solid #e0e0e0;
        font-size: 14px;
        color: #333;
    }
    .custom-footer img {
        height: 40px;
        vertical-align: middle;
        margin-right: 10px;
    }
    </style>
    <div class="custom-footer">
        <strong>Medical Artificial Intelligence Lab || Contact Email: info@mailab.io </strong> – © 2025 All Rights Reserved

    </div>
    """,
    unsafe_allow_html=True
)
