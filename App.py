import streamlit as st
import pandas as pd
import calendar
from datetime import datetime, timedelta
from io import BytesIO
from dateutil.parser import parse
import re

st.set_page_config(page_title="Usage Allocation Generator", layout="wide")
st.title("📊 Monthly Usage Allocation Journal Generator")

uploaded_file = st.file_uploader("Upload the invoice CSV file", type=["csv"])

# --- Robust date parser ---
def try_parse_date(x):
    try:
        return parse(str(x), dayfirst=True)
    except Exception:
        return pd.NaT

# --- Adjust AccountCode properly ---
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

if uploaded_file:
    df = pd.read_csv(uploaded_file)

    # --- Clean column headers ---
    df.columns = df.columns.str.strip()

    # --- Validate required columns ---
    required_columns = [
        "Start Date", "End Date", "Net", "Invoice Number",
        "Journal Month", "Account Code"
    ]
    missing = [col for col in required_columns if col not in df.columns]

    if missing:
        st.error(f"Missing required column(s): {', '.join(missing)}")
        st.stop()

    # --- Parse Start and End Dates safely ---
    df["Start Date"] = df["Start Date"].apply(try_parse_date)
    df["End Date"] = df["End Date"].apply(try_parse_date)

    # --- Flag and display invalid date rows ---
    invalid_dates = df[df["Start Date"].isna() | df["End Date"].isna()]
    if not invalid_dates.empty:
        st.warning(f"⚠️ {len(invalid_dates)} row(s) have invalid Start or End Dates and will be skipped.")
        st.dataframe(invalid_dates)

    # --- Filter valid dates ---
    valid_df = df.dropna(subset=["Start Date", "End Date"])

    # --- Drop rows with missing or invalid Net values ---
    def safe_float(x):
        try:
            return float(str(x).replace(",", "").strip())
        except:
            return None

    valid_df["Net"] = valid_df["Net"].apply(safe_float)
    valid_df = valid_df.dropna(subset=["Net"])

    total_rows = len(df)
    output_rows = []
    error_rows = 0
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
            cumulative = 0.0

            for i, s in enumerate(segments):
                if i < len(segments) - 1:
                    amount = round(s["unrounded_amount"], 2)
                    cumulative += amount
                else:
                    amount = round(net - cumulative, 2)

                narration = f"Adjustment for Deferred COGS for {journal_month} for {invoice_number}"

                # --- Apply Net sign logic for Account Codes ---
                if net < 0:
                    # Account Code 7 → positive, Account Code 3 → negative
                    if account_code.strip().startswith("7"):
                        amount = abs(amount)
                    elif account_code.strip().startswith("3"):
                        amount = -abs(amount)
                else:
                    # Account Code 7 → negative, Account Code 3 → positive
                    if account_code.strip().startswith("7"):
                        amount = -abs(amount)
                    elif account_code.strip().startswith("3"):
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

            # --- Add reversed duplicates ---
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
            error_rows += 1
            st.error(f"❌ Row {index + 1}: {e}")
            error_log.append({
                "Row": index + 1,
                "Reason": str(e),
                "Invoice Number": row.get("Invoice Number", "N/A"),
                "Start Date": row.get("Start Date", "N/A"),
                "End Date": row.get("End Date", "N/A"),
                "Net": row.get("Net", "N/A")
            })

    # --- Create final DataFrame and remove zero values ---
    output_df = pd.DataFrame(output_rows)
    output_df = output_df[output_df["*Amount"] != 0]

    if not output_df.empty:
        st.success("✅ Allocation complete. Download your processed file below:")

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

        # --- Reconciliation ---
        uploaded_total_net = valid_df["Net"].sum()
        processed_total_net = output_df["*Amount"].sum()
        difference = uploaded_total_net - processed_total_net

        st.subheader("📊 Reconciliation Summary")
        if abs(difference) < 0.01:
            st.markdown(
                f"<span style='color:green; font-weight:bold;'>✅ Totals Match</span><br>"
                f"**Total Net Uploaded:** {uploaded_total_net:,.2f}<br>"
                f"**Total Net Processed:** {processed_total_net:,.2f}<br>"
                f"**Difference:** {difference:,.2f}",
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"<span style='color:red; font-weight:bold;'>⚠ Totals Do Not Match</span><br>"
                f"**Total Net Uploaded:** {uploaded_total_net:,.2f}<br>"
                f"**Total Net Processed:** {processed_total_net:,.2f}<br>"
                f"**Difference:** {difference:,.2f}",
                unsafe_allow_html=True
            )

    st.info(f"""
    📋 **Status Summary**
    - 📄 Total rows uploaded: **{total_rows}**
    - ✅ Successfully processed: **{completed_rows}**
    - ❌ Rows with errors/skipped: **{total_rows - completed_rows}**
    """)

    if error_log:
        st.subheader("📝 Remarks on Skipped/Error Rows")
        st.dataframe(pd.DataFrame(error_log))
