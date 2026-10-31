import pandas as pd

data = pd.read_csv("unsd-citypopulation-year-both.csv")

data_last_261 = data.tail(261)
data_last_261.to_csv("footnotes.csv", index=False)

filtered_data = data[data["Country or Area"].isin(["Netherlands (Kingdom of the)", "Belgium", "Luxembourg"])]


filtered_data = filtered_data.copy()
filtered_data["footnote_id"] = pd.to_numeric(
	filtered_data["Value Footnotes"], errors="coerce"
).astype("Int64").astype("string")

footnotes = data_last_261[["Country or Area", "Year"]].copy()
footnotes["Country or Area"] = pd.to_numeric(
	footnotes["Country or Area"], errors="coerce"
).astype("Int64").astype("string")
footnotes = footnotes.rename(columns={"Country or Area": "footnote_id", "Year": "footnotes"})

merged_data = filtered_data.merge(footnotes, on="footnote_id", how="left")
merged_data = merged_data.drop(columns=["footnote_id", "Value Footnotes"])
merged_data.to_csv("Benelux_data.csv", index=False)
