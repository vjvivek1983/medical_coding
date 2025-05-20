import csv
import json
import pandas as pd
import streamlit as st
from PyPDF2 import PdfReader
from dotenv import load_dotenv
import time
import streamlit.components.v1 as components
from base64 import b64encode
import io
import xlsxwriter
import os

# from customer_pdf_to_bronze import *
# from jjpl_ledger_data import *
# from databricks import sql
# from recon_gold import *

st.set_page_config(page_title="LumenAI Reconciler", page_icon="https://s3.amazonaws.com/lumenai.eucloid.com/assets/images/icons/logo.svg", layout="wide", initial_sidebar_state="auto", menu_items=None)

def add_logo_btn1():
    logo_url = "https://lumenai.eucloid.com/assets/images/logo.svg"
    back_button_url = "https://product.lumenai.eucloid.com/home"

    st.sidebar.markdown(
        f"""
        <div style="display: flex; justify-content: flex-start; align-items: center; padding-bottom: 20px;">
            <a href="{back_button_url}" target="_self">
                <img src="https://s3.amazonaws.com/lumenai.eucloid.com/assets/images/icons/back-btn.svg" alt="<-" width="20" height="20" style="margin-right: 10px;">
            </a>
            <div style="text-align: center;">
                <a href="https://product.lumenai.eucloid.com/login" target="_self">
                    <img src="{logo_url}" alt="Logo" width="225" height="fit-content">
                </a>
            </div>
        </div>
    """,
        unsafe_allow_html=True
    )

def remove_existing_files(extension):
    for filename in os.listdir('.'):
        if filename.endswith(extension):
            os.remove(filename)

def generate_excel_download(df):
    towrite = io.BytesIO()
    df.to_excel(towrite, index=False, engine='xlsxwriter')
    towrite.seek(0)
    b64 = b64encode(towrite.read()).decode()
    return f'<a href="data:application/octet-stream;base64,{b64}" download="reconciled_report.xlsx">Download Excel file</a>'

def write_messages_to_file(messages, filename="reconciliation_messages.txt"):
    with open(filename, "w") as file:
        for message in messages:
            file.write(message + "\n")
    return filename

def main():
    if 'accept_reject_status' not in st.session_state:
        st.session_state.accept_reject_status = {}
    if 'predictions' not in st.session_state:
        st.session_state.predictions = None
    if 'text_file_path' not in st.session_state:
        st.session_state.text_file_path = None

    add_logo_btn1()

    st.sidebar.markdown("<hr>", unsafe_allow_html=True)
    st.sidebar.markdown("<h3 style='margin-bottom: 10px;'>Instructions</h3>", unsafe_allow_html=True)
    st.sidebar.markdown("""
        <div style="padding-left: 10px; line-height: 1.6;">
            <strong>1.</strong> Upload a file set (PDF and Excel) file using the file uploader below.<br><br>
            <strong>2.</strong> Wait for the model to process the data from pdf file and the excel file.<br><br>
            <strong>3.</strong> Click 'Generate Report' to reconcile data and download the report of non reconciled data.
            <br><br>
        </div>
    """, unsafe_allow_html=True)

    uploaded_files = st.sidebar.file_uploader("Choose up to 2 files", type=['pdf', 'xlsx'], accept_multiple_files=True)

    main_placeholder = st.empty()

    if uploaded_files:
        if len(uploaded_files) > 2:
            st.warning("Please upload up to 2 files only.")
        else:
            col1, col2 = st.columns(2)
            dataframe_height = 600

            for i, uploaded_file in enumerate(uploaded_files):
                file_bytes = uploaded_file.read()

                if uploaded_file.name.endswith('.pdf'):
                    pdf_path = f"./temp_{uploaded_file.name}"
                    with open(pdf_path, "wb") as f:
                        f.write(file_bytes)

                    base64_pdf = b64encode(file_bytes).decode('utf-8')
                    iframe_style = "width: 100%; height: 600px; border: none;"
                    pdf_display = f'''
                                <iframe src="data:application/pdf;base64,{base64_pdf}" style="{iframe_style}" type="application/pdf">
                                    PDF Viewer
                                </iframe>
                                '''
                    if i == 0:
                        col1.markdown(f"##### {uploaded_file.name} (File {i + 1}):")
                        col1.markdown(pdf_display, unsafe_allow_html=True)
                    else:
                        col2.markdown(f"##### {uploaded_file.name} (File {i + 1}):")
                        col2.markdown(pdf_display, unsafe_allow_html=True)

                elif uploaded_file.name.endswith('.xlsx'):
                    df = pd.read_excel(uploaded_file)
                    vdf = pd.read_excel(uploaded_file, header=1)

                    sap_excel_file_path = f"./SAP_{uploaded_file.name}"
                    with open(sap_excel_file_path, "wb") as f:
                        f.write(file_bytes)

                    if i == 0:
                        col1.markdown(f"##### {uploaded_file.name} (File {i + 1}):")
                        col1.dataframe(vdf, height=dataframe_height)
                    else:
                        col2.markdown(f"##### {uploaded_file.name} (File {i + 1}):")
                        col2.dataframe(vdf, height=dataframe_height)

            if st.button("Generate Report"):
                if len(uploaded_files) == 2:
                    try:
                        try:
                            silver_df_customer = pdf_to_bronze_csv(pdf_path)
                        except UnboundLocalError:
                            st.error("Please upload the PDF file.")
                            remove_existing_files('.pdf')
                            remove_existing_files('.xlsx')
                            return

                        try:
                            sdf_cleaned = clean_ledger_data(sap_excel_file_path)
                        except:
                            st.error("Please upload the Excel file.")
                            remove_existing_files('.pdf')
                            remove_existing_files('.xlsx')
                            return

                        spark_silver_customer_df = pandas_to_spark_silver_customer(silver_df_customer)
                        spark_cleaned_df = pandas_to_spark_cleaned(sdf_cleaned)

                        df_gold_pd, messages = perform_reconciliation(spark_silver_customer_df, spark_cleaned_df)

                        if df_gold_pd is not None and not df_gold_pd.empty:
                            st.success("Reconciliation completed!")
                            st.write(df_gold_pd)

                            for message in messages:
                                st.info(message)

                            download_link = generate_excel_download(df_gold_pd)
                            st.markdown(download_link, unsafe_allow_html=True)

                        elif df_gold_pd is not None and df_gold_pd.empty:
                            for message in messages:
                                st.info(message)
                            remove_existing_files('.pdf')
                            remove_existing_files('.xlsx')
                    except Exception as e:
                        st.error(f"An error occurred during reconciliation: {str(e)}")
                        st.exception(e)
                        remove_existing_files('.pdf')
                        remove_existing_files('.xlsx')
                else:
                    st.error("Please upload 2 files for reconciliation.")

    user_message = st.text_area("Enter your message here:", height=68, key="user_message_area")
    submit_button = st.button("Submit")

    if submit_button and user_message:
        os.makedirs("/home/vj/ICD_TREE_SEARCH/text_files_en", exist_ok=True)
        text_file_path = os.path.join("/home/vj/ICD_TREE_SEARCH/text_files_en", "user_input.txt")
        with open(text_file_path, "w") as f:
            f.write(user_message)
        st.session_state.text_file_path = text_file_path
        if os.path.exists("/home/vj/ICD_TREE_SEARCH/text_files_en/output.json"):
            os.remove("/home/vj/ICD_TREE_SEARCH/text_files_en/output.json")
        st.write("Processing ICD code predictions: ")

        os.system("python /home/vj/ICD_TREE_SEARCH/automated-clinical-coding-llm/run_tree_search.py --model_name gpt-4o --input_dir /home/vj/ICD_TREE_SEARCH/text_files_en --output_file /home/vj/ICD_TREE_SEARCH/text_files_en/output.json")

        predictions = json.loads(open("/home/vj/ICD_TREE_SEARCH/text_files_en/output.json","r").read())['user_input.txt']
        
        st.session_state.predictions = predictions

    if st.session_state.predictions:
        
            
            
        st.subheader("Predictions:")
        for codes in enumerate(st.session_state.predictions):
            
            
            
                
            col1, col2, col3, col4 = st.columns([2, 1, 1, 2])

            with col1:
                st.write(f"{codes[1]}")

            with col2:
                if st.button("Accept", key=f"accept_{codes}"):
                    st.session_state.accept_reject_status[codes] = "accepted"

            with col3:
                if st.button("Reject", key=f"reject_{codes}"):
                    st.session_state.accept_reject_status[codes] = "rejected"

            with col4:
                status = st.session_state.accept_reject_status.get(codes, None)
                if status == "accepted":
                    st.markdown("<span style='color:green'>✅ Accepted</span>", unsafe_allow_html=True)
                elif status == "rejected":
                    st.markdown("<span style='color:red'>❌ Rejected</span>", unsafe_allow_html=True)
                else:
                    st.markdown("<span style='color:gray'>— Pending</span>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
