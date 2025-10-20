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
import time
from io import BytesIO
# ------------------------------
# Streamlit Page Configuration & Branding
# ------------------------------
st.set_page_config(page_title="MRIQC App", layout="wide")

st.markdown("""
# MRIQC Web App for MRI Image Quality Assessment

The Web-MRIQC App provides an intuitive web interface for running Quality Control on MRI datasets acquired in DICOM formats. The App offers users the ability to compute Image Quality Metrics (IQMs) for neuroimaging studies.
This web-based solution implements the original MRIQC standalone application in a user-friendly interface accessible from any device, without the need for software installation or access to resource-intensive computers. Thus, simplifying the quality control workflow. For a comprehensive understanding of the IQMs computed by MRIQC, as well as details on the original MRIQC implementation, refer to the official MRIQC documentation: https://mriqc.readthedocs.io.
""",
            unsafe_allow_html=True
            )

st.markdown(
    """
## How to Use:
The app enables users to upload T1w, T2w, DWI, BOLD fMRI, or ASL DICOM files as a folder or zipped format, convert them to the Standard Brain Imaging Data Structure (BIDS) format using dcm2bids [1] via dcm2niiX [2], and then process the IQMs using MRIQC [3]. The resulting reports can be downloaded for further analysis. To use, follow the following steps:

1. Enter Subject ID (optional)
2. Enter the Session ID (optional, e.g, baseline, follow up, etc)
3. Select your preferred modality for analysis (T1w, T2w, DWI, BOLD fMRI, or ASL)
4. Upload a zipped file/folder containing T1w, T2w, DWI, BOLD fMRI, or ASL DICOM images by dragging and dropping the zipped file or uploading using the browse file option
5. Click DICOM → BIDS Conversion
6. Once BIDS converted, you will see the notification: DICOM to BIDS conversion complete
7. Click Send BIDS to Web for MRIQC or if you want the BIDS format, Click Download BIDS Dataset to your device.
8. Send the converted BIDS images to MRIQC by clicking Send BIDS to Web for MRIQC  for generating the IQMs
9. Depending on your internet connection, this can between 5-10 minutes to get your results for a single participant.
10. When completed, you can view the report on the web App or download the report of the IQM by clicking the "Download MRIQC results" button including the csv export.

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

# ------------------------------
# Helper Functions
# ------------------------------


def generate_dcm2bids_config(temp_dir: Path) -> Path:
    config = {
        "descriptions": [
            # Anatomical Imaging
            {
                "datatype": "anat",
                "suffix": "T1w",
                "criteria": {
                    "SeriesDescription": "*T1*",
                    "ImageType": ["ORIGINAL", "(?i).*(PRIMARY|PERMANY|OTHER).*"]
                },
                "sidecar_changes": {"ProtocolName": "T1w"}
            },
            {
                "datatype": "anat",
                "suffix": "T2w",
                "criteria": {
                    "SeriesDescription": "*T2*",
                    "ImageType": ["ORIGINAL", "(?i).*(PRIMARY|PERMANY).*"]
                },
                "sidecar_changes": {"ProtocolName": "T2w"}
            },
            {
                "datatype": "anat",
                "suffix": "FLAIR",
                "criteria": {
                    "SeriesDescription": "*FLAIR*",
                    "ImageType": ["ORIGINAL", "(?i).*(PRIMARY|PERMANY).*"]
                }
            },

            # Functional Imaging
            {
                "datatype": "func",
                "suffix": "bold",
                "criteria": {
                    "SeriesDescription": "*BOLD*",
                    "ImageType": ["ORIGINAL", "(?i).*(PRIMARY|FMRI|OTHER).*"]
                },
                "sidecar_changes": {"TaskName": "rest"}
            },
            {
                "datatype": "func",
                "suffix": "sbref",
                "criteria": {
                    "SeriesDescription": "*SBRef*",
                    "ImageType": ["ORIGINAL", "(?i).*(PRIMARY|FMRI|OTHER).*"]
                }
            },

            # Diffusion Imaging
            {
                "datatype": "dwi",
                "suffix": "dwi",
                "criteria": {
                    "SeriesDescription": "*DWI*|*DTI*",
                    "ImageType": ["ORIGINAL", "(?i).*(PRIMARY|DIFFUSION).*"]
                },
                "sidecar_changes": {
                    "PhaseEncodingDirection": "j",
                    "TotalReadoutTime": 0.028
                }
            },

            # Field Maps
            {
                "datatype": "fmap",
                "suffix": "phasediff",
                "criteria": {
                    "SeriesDescription": "*FMRI_DISTORTION*",
                    "ImageType": ["ORIGINAL", "(?i).*(P|PHASE).*"]
                }
            },
            {
                "datatype": "fmap",
                "suffix": "magnitude",
                "criteria": {
                    "SeriesDescription": "*FMRI_DISTORTION*",
                    "ImageType": ["ORIGINAL", "(?i).*(M|MAG).*"]
                }
            },

            # Perfusion Imaging
            {
                "datatype": "perf",
                "suffix": "asl",
                "criteria": {
                    "SeriesDescription": "*ASL*|*Perfusion*",
                    "ImageType": ["ORIGINAL", "(?i).*(PRIMARY|PERFUSION).*"]
                }
            },

            # Task-Based fMRI(Example for different tasks)
            {
                "datatype": "func",
                "suffix": "bold",
                "criteria": {
                    "SeriesDescription": "*Nback*",
                    "ImageType": ["ORIGINAL", "(?i).*(PRIMARY|FMRI).*"]
                },
                "sidecar_changes": {"TaskName": "nback"}
            },

            # Multi-echo Sequences
            {
                "datatype": "anat",
                "suffix": "MESE",
                "criteria": {
                    "SeriesDescription": "*MultiEcho*",
                    "ImageType": ["ORIGINAL", "(?i).*(PRIMARY|MULTIECHO).*"]
                }
            }
        ],
        "default_entities": {
            "subject": "{subject}",
            "session": "{session}"
        }
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


def classify_from_metadata(meta):
    """
    Classifies based on metadata if and only if ImageType includes 'ORIGINAL'.
    """
    image_type = meta.get("ImageType", [])
    if isinstance(image_type, str):
        image_type = [image_type]

    if not any("original" in t.lower() for t in image_type):
        return None, None  # Skip derived images

    desc = (meta.get("SeriesDescription", "") + " " +
            meta.get("ProtocolName", "")).lower()
    pulse = meta.get("PulseSequenceName", "").lower()

    if "t1" in desc and "flair" not in desc:
        return "anat", "T1w"
    elif "t2" in desc:
        return "anat", "T2w"
    elif "flair" in desc or "fluid" in desc:
        return "anat", "FLAIR"
    elif "dwi" in desc or "dti" in desc:
        return "dwi", "dwi"
    elif "bold" in desc or "fmri" in desc or "functional" in desc or "activation" in desc or "epi" in pulse:
        return "func", "bold"
    elif "asl" in desc or "perfusion" in desc:
        return "perf", "asl"
    else:
        return None, None


def classify_and_move_original_files(bids_out: Path, subj_id: str, ses_id: str):
    tmp_folder = bids_out / "tmp_dcm2bids" / f"sub-{subj_id}_ses-{ses_id}"
    if not tmp_folder.exists():
        return

    sub_dir = bids_out / f"sub-{subj_id}"
    ses_dir = sub_dir / f"ses-{ses_id}" if ses_id else sub_dir
    ses_dir.mkdir(parents=True, exist_ok=True)

    modality_paths = {
        "anat": ses_dir / "anat",
        "dwi":  ses_dir / "dwi",
        "func": ses_dir / "func",
        "perf": ses_dir / "perf"
    }

    # Loop over JSON sidecars only
    for json_file in tmp_folder.rglob("*.json"):
        try:
            with open(json_file, "r") as jf:
                meta = json.load(jf)
        except Exception:
            st.warning(f"Could not read JSON: {json_file.name}")
            continue

        # Check for ORIGINAL in ImageType
        image_type = meta.get("ImageType", [])
        if isinstance(image_type, str):
            image_type = [image_type]
        if not any("original" in item.lower() for item in image_type):
            st.info(f"Discarded non-original: {json_file.name}")
            continue

        # Determine modality from metadata
        desc = (meta.get("SeriesDescription", "") + " " +
                meta.get("ProtocolName", "")).lower()
        pulse = meta.get("PulseSequenceName", "").lower()

        if "t1" in desc and "flair" not in desc:
            modality, suffix = "anat", "T1w"
        elif "t2" in desc:
            modality, suffix = "anat", "T2w"
        elif "flair" in desc or "fluid" in desc:
            modality, suffix = "anat", "FLAIR"
        elif "dwi" in desc or "dti" in desc:
            modality, suffix = "dwi", "dwi"
        elif "bold" in desc or "fmri" in desc or "functional" in desc or "activation" in desc or "epi" in pulse:
            modality, suffix = "func", "bold"
        elif "asl" in desc or "perfusion" in desc:
            modality, suffix = "perf", "asl"
        else:
            st.info(f"Unclassified: {json_file.name}")
            continue

        # Locate matching NIfTI image
        nii_file = json_file.with_suffix(".nii.gz")
        if not nii_file.exists():
            nii_file = json_file.with_suffix(".nii")
        if not nii_file.exists():
            st.warning(f"No matching NIfTI for: {json_file.name}")
            continue

        target_dir = modality_paths[modality]
        target_dir.mkdir(parents=True, exist_ok=True)

        # Compose filenames
        base_name = f"sub-{subj_id}"
        if ses_id:
            base_name += f"_ses-{ses_id}"
        base_name += f"_{suffix}"

        new_json_path = target_dir / f"{base_name}.json"
        new_nii_path = target_dir / (f"{base_name}.nii.gz")

        # Move both
        shutil.move(str(json_file), str(new_json_path))
        shutil.move(str(nii_file), str(new_nii_path))
        st.success(f"Moved: {new_json_path.name} and {new_nii_path.name}")

    # Cleanup
    shutil.rmtree(tmp_folder.parent, ignore_errors=True)
    st.info("Finished organizing ORIGINAL NIfTI + JSON pairs.")


# This line replaces your old move_files_in_tmp()
move_files_in_tmp = classify_and_move_original_files


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
- Perf: ASL perfusion scans

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
                        'zip', root_dir=folder_path)


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
    ses_id = st.text_input("Session ID (optional)", value="baseline")

    selected_modalities = st.multiselect(
        "Select MRIQC modalities:",
        ["T1w", "T2w", "bold"],
        default=["T1w"]
    )

    col1, col2 = st.columns(2)
    with col1:
        n_procs = st.selectbox("CPU Cores to Use", [4, 8, 12, 16], index=0)
    with col2:
        mem_gb = st.selectbox("Memory Allocation (GB)",
                              [16, 32, 48, 64], index=0)

    API_BASE = "http://20.184.131.164:8000"

    dicom_zip = st.file_uploader("Upload DICOM ZIP", type=["zip"])

    if dicom_zip:
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

                classify_and_move_original_files(bids_out, subj_id, ses_id)
                create_bids_top_level_files(bids_out, subj_id)

                bids_zip_path = temp_dir / "bids_dataset.zip"
                zip_directory(bids_out, bids_zip_path)
                st.success("DICOM to BIDS conversion complete!")

                with open(bids_zip_path, "rb") as f:
                    st.download_button(
                        "Download BIDS Dataset",
                        data=f,
                        file_name="BIDS_dataset.zip",
                        mime="application/zip"
                    )

                st.session_state.temp_dir = str(temp_dir)
                st.session_state.bids_zip_path = str(bids_zip_path)

        if selected_modalities:
            st.markdown("### ✅ Selected Modalities for MRIQC")
            st.success(
                f"You have selected: `{', '.join(selected_modalities)}`")
        else:
            st.warning("⚠️ No modalities selected!")

        if st.button("Send BIDS to Web for MRIQC"):
            if "temp_dir" not in st.session_state:
                st.error("No BIDS dataset found. Please run the conversion first.")
                st.stop()

            temp_dir = Path(st.session_state.temp_dir)
            bids_zip_path = Path(st.session_state.bids_zip_path)

            if not bids_zip_path.exists():
                st.error(f"BIDS zip not found: {bids_zip_path}")
                st.stop()

            modalities_str = " ".join(selected_modalities)
            st.info(f"📦 Modalities: {modalities_str}")

            with open(bids_zip_path, 'rb') as f:
                file_content = f.read()

            files = {'bids_zip': ('bids_dataset.zip',
                                  file_content, 'application/zip')}
            data = {
                'participant_label': subj_id,
                'modalities': modalities_str,
                'session_id': ses_id or "",
                'n_procs': str(n_procs),
                'mem_gb': str(mem_gb)
            }

            st.info(f"🚀 Sending to: {API_BASE}/run-mriqc")
            st.warning("⏳ Processing takes ~10 minutes. Please wait...")

            progress_bar = st.progress(0)
            status_text = st.empty()

            try:
                progress_bar.progress(10)
                status_text.text("Uploading BIDS dataset...")

                with st.spinner("Processing on server... This may take several minutes."):
                    # ✅ correct var (data) + stream enabled
                    response = requests.post(
                        f"{API_BASE}/run-mriqc",
                        files=files,
                        data=data,                    # <-- FIXED
                        timeout=(120, 7200),
                        stream=True
                    )

                # If backend returned an error, surface it now
                if response.status_code != 200:
                    # try to show structured detail if available
                    try:
                        detail = response.json().get("detail")
                        st.error(
                            f"❌ MRIQC failed ({response.status_code}): {detail}")
                    except Exception:
                        st.error(f"❌ MRIQC failed ({response.status_code})")
                        st.error(response.text[:800])
                    st.stop()

                progress_bar.progress(50)
                status_text.text(
                    "Processing completed, downloading results...")

                # ✅ Save streamed ZIP to disk with progress
                result_zip_path = Path("mriqc_results.zip")
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0

                with open(result_zip_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        f.write(chunk)
                        if total:
                            downloaded += len(chunk)
                            # map 50->95% during download
                            pct = 50 + int(45 * (downloaded / total))
                            progress_bar.progress(min(pct, 95))

                # ✅ Validate the ZIP
                if not result_zip_path.exists() or result_zip_path.stat().st_size == 0:
                    st.error("❌ Received empty file from backend.")
                    st.stop()

                try:
                    with zipfile.ZipFile(result_zip_path, "r") as zf:
                        zf.testzip()  # quick integrity check
                except zipfile.BadZipFile:
                    ct = response.headers.get("content-type", "")
                    cd = response.headers.get("content-disposition", "")
                    st.error("❌ Response was not a valid ZIP file.")
                    st.info(f"content-type: {ct}")
                    st.info(f"content-disposition: {cd}")
                    st.stop()

                progress_bar.progress(96)
                status_text.text("Extracting results...")

                # ✅ Extract to a fresh folder
                extract_dir = Path("mriqc_results")
                if extract_dir.exists():
                    shutil.rmtree(extract_dir, ignore_errors=True)
                extract_dir.mkdir(parents=True, exist_ok=True)

                with zipfile.ZipFile(result_zip_path, "r") as zf:
                    zf.extractall(extract_dir)

                progress_bar.progress(100)
                status_text.text("Complete!")
                st.success(
                    "✅ MRIQC completed successfully and results were received.")

                # ---- UI: Download button
                with open(result_zip_path, "rb") as f:
                    st.download_button(
                        label="⬇️ Download MRIQC Results ZIP",
                        data=f,
                        file_name=f"mriqc_results_{subj_id}.zip",
                        mime="application/zip"
                    )

                # ---- UI: Preview contents (TSV + HTML)
                st.subheader("📁 Results Summary")
                files_listed = [p.relative_to(extract_dir).as_posix()
                                for p in extract_dir.rglob("*") if p.is_file()]
                if files_listed:
                    st.write(f"Found **{len(files_listed)}** files.")
                    st.code("\n".join(sorted(files_listed[:100])))

                tsv_files = list(extract_dir.rglob("*.tsv"))
                if tsv_files:
                    st.subheader("📊 Quality Metrics (TSV)")
                    for tsv in tsv_files:
                        st.write(f"**{tsv.name}**")
                        try:
                            df = pd.read_csv(tsv, sep="\t")
                            st.dataframe(df)
                        except Exception as e:
                            st.warning(f"Could not read {tsv.name}: {e}")
                else:
                    st.info("No TSV metrics found.")

                html_files = list(extract_dir.rglob("*.html"))
                if html_files:
                    st.subheader("🧠 MRIQC HTML Reports")
                    for html_path in html_files:
                        try:
                            with open(html_path, "r", encoding="utf-8") as fh:
                                st.components.v1.html(
                                    fh.read(), height=700, scrolling=True)
                        except Exception as e:
                            st.warning(
                                f"Could not render {html_path.name}: {e}")
                else:
                    st.info("No HTML reports found.")
            except requests.exceptions.Timeout:
                st.error("❌ Request timed out — processing took too long.")
            except Exception as e:
                st.error(f"❌ Unexpected error: {e}")


# ------------------------------
# Footer and Branding
# ------------------------------

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

if __name__ == "__main__":
    main()
