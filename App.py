import streamlit as st
import pandas as pd
import calendar
from datetime import datetime, timedelta
from io import BytesIO
from dateutil.parser import parse
import re

st.set_page_config(page_title="Usage Allocation Generator", layout="wide")
st.title("📊 COGS: Monthly Usage Allocation Journal Generator")

# -----------------------------
# DOWNLOAD TEMPLATE
# -----------------------------
st.subheader("📥 Download Template")

template_df = pd.DataFrame({
    "Start Date": ["01-01-2026"],
    "End Date": ["31-01-2026"],
    "Net": [1000],
    "Invoice Number": ["INV-001"],
    "Journal Month": ["Jan-2026"],
    "Account Code": ["70000"]
})

def download_template(df):
    buffer = BytesIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue()

st.download_button(
    label="⬇ Download CSV Template",
    data=download_template(template_df),
    file_name="usage_allocation_template.csv",
    mime="text/csv"
)

st.caption("""
Template Rules:
• Dates format: 01-01-2026 or 01/01/2026  
• Net must be numeric  
• Account Code normally starts with 3 or 7  
""")

# -----------------------------
# FILE UPLOAD
# -----------------------------
uploaded_file = st.file_uploader("Upload the invoice CSV file", type=["csv"])

# -----------------------------
# FUNCTIONS
# -----------------------------

def try_parse_date(x):
    try:
        return parse(str(x), dayfirst=True)
    except:
        return pd.NaT

def adjust_account_code(code):
    try:
        match = re.match(r"(\d+)(.*)", str(code))
        if match:
            number_part = int(match.group(1))
            suffix = match.group(2)
            adjusted_number = number_part - 45000
            return f"{adjusted_number}{suffix}"
        else:
            return code
    except:
        return code

# -----------------------------
# PROCESS FILE
# -----------------------------
if uploaded_file:

    df = pd.read_csv(uploaded_file)
    df.columns = df.columns.str.strip()

    required_columns = [
        "Start Date",
        "End Date",
        "Net",
        "Invoice Number",
        "Journal Month",
        "Account Code"
    ]

    missing = [col for col in required_columns if col not in df.columns]

    if missing:
        st.error(f"Missing required column(s): {', '.join(missing)}")
        st.stop()

    df["Start Date"] = df["Start Date"].apply(try_parse_date)
    df["End Date"] = df["End Date"].apply(try_parse_date)

    invalid_dates = df[df["Start Date"].isna() | df["End Date"].isna()]

    if not invalid_dates.empty:
        st.warning(f"⚠️ {len(invalid_dates)} row(s) have invalid dates and will be skipped.")
        st.dataframe(invalid_dates)

    valid_df = df.dropna(subset=["Start Date", "End Date"])

    def safe_float(x):
        try:
            return float(str(x).replace(",", "").strip())
        except:
            return None

    valid_df["Net"] = valid_df["Net"].apply(safe_float)
    valid_df = valid_df.dropna(subset=["Net"])

    total_rows = len(df)
    output_rows = []
    completed_rows = 0
    error_log = []

    for index, row in valid_df.iterrows():

        try:

            start_date = row["Start Date"]
            end_date = row["End Date"]
            net = row["Net"]

            invoice_number = str(row["Invoice Number"]).strip()
            journal_month = str(row["Journal Month"]).strip()
            account_code = str(row["Account Code"]).strip()

            current = start_date.replace(day=1)
            segments = []

            while current <= end_date:

                month_start = current
                last_day = calendar.monthrange(current.year, current.month)[1]
                month_end = current.replace(day=last_day)

                segment_start = max(start_date, month_start)
                segment_end = min(end_date, month_end)

                usage_days = (segment_end - segment_start).days + 1

                if usage_days > 0:
                    segments.append({
                        "date": month_end,
                        "usage_days": usage_days
                    })

                current += timedelta(days=32)
                current = current.replace(day=1)

            total_days = sum(s["usage_days"] for s in segments)

            if total_days == 0:
                raise ValueError("0 usage days in range")

            for s in segments:
                s["unrounded_amount"] = (s["usage_days"] / total_days) * net

            rounded_segments = []
            cumulative = 0

            for i, s in enumerate(segments):

                if i < len(segments) - 1:
                    amount = round(s["unrounded_amount"], 2)
                    cumulative += amount
                else:
                    amount = round(net - cumulative, 2)

                narration = f"Adjustment for Deferred COGS for {journal_month} for {invoice_number}"

                if net < 0:

                    if account_code.startswith("7"):
                        amount = abs(amount)

                    elif account_code.startswith("3"):
                        amount = -abs(amount)

                else:

                    if account_code.startswith("7"):
                        amount = -abs(amount)

                    elif account_code.startswith("3"):
                        amount = abs(amount)

                rounded_segments.append({
                    "*Narration": narration,
                    "*Date": s["date"].strftime("%d-%m-%y"),
                    "Description": narration,
                    "*AccountCode": account_code,
                    "*TaxRate": "Tax Exempt",
                    "*Amount": amount,
                    "TrackingName1": "",
                    "TrackingOption1": "",
                    "TrackingName2": "",
                    "TrackingOption2": ""
                })

            duplicated_segments = []

            for seg in rounded_segments:

                if seg["*Amount"] == 0:
                    continue

                duplicated = seg.copy()
                duplicated["*Amount"] = -duplicated["*Amount"]
                duplicated["*AccountCode"] = adjust_account_code(seg["*AccountCode"])

                duplicated_segments.append(duplicated)

            output_rows.extend(rounded_segments + duplicated_segments)
            completed_rows += 1

        except Exception as e:

            error_log.append({
                "Row": index + 1,
                "Reason": str(e),
                "Invoice Number": row.get("Invoice Number", "N/A")
            })

    output_df = pd.DataFrame(output_rows)

    if not output_df.empty:

        output_df = output_df[output_df["*Amount"] != 0]

        # -----------------------------
        # PREVIEW SECTION
        # -----------------------------
        st.subheader("🔎 Allocation Preview")

        preview_df = output_df.sort_values(by=["*Date", "*AccountCode"])

        st.dataframe(
            preview_df,
            use_container_width=True,
            height=400
        )

        preview_total = preview_df["*Amount"].sum()

        st.metric(
            label="Total Journal Amount",
            value=f"{preview_total:,.2f}"
        )

        # -----------------------------
        # DOWNLOAD RESULT
        # -----------------------------
        def convert_df(df):
            buffer = BytesIO()
            df.to_csv(buffer, index=False)
            return buffer.getvalue()

        st.download_button(
            label="📥 Download Result CSV",
            data=convert_df(output_df),
            file_name="usage_allocation_output.csv",
            mime="text/csv"
        )

        # -----------------------------
        # RECONCILIATION SUMMARY
        # -----------------------------
        st.subheader("📊 Reconciliation Summary")

        uploaded_total_net = valid_df["Net"].sum()
        processed_total_net = output_df["*Amount"].sum()

        if abs(processed_total_net) < 0.01:

            st.success(f"""
✅ Journals Balanced

Uploaded Net (Source): {uploaded_total_net:,.2f}  
Total Journal Net: {processed_total_net:,.2f}

Result: Income and Deferred COGS entries offset correctly.
""")

        else:

            st.error(f"""
⚠ Journal Not Balanced

Uploaded Net (Source): {uploaded_total_net:,.2f}  
Total Journal Net: {processed_total_net:,.2f}

Please review allocation logic.
""")

    # -----------------------------
    # STATUS SUMMARY
    # -----------------------------
    st.info(f"""
📋 Status Summary

Total rows uploaded: {total_rows}  
Successfully processed: {completed_rows}  
Skipped rows: {total_rows - completed_rows}
""")

    if error_log:
        st.subheader("📝 Skipped/Error Rows")
        st.dataframe(pd.DataFrame(error_log))
