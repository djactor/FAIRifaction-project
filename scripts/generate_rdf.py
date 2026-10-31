import argparse
import re
from pathlib import Path

import pandas as pd
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD

ROOT = Path(__file__).resolve().parent.parent

QB = Namespace("http://purl.org/linked-data/cube#")
SDMX_DIM = Namespace("http://purl.org/linked-data/sdmx/2009/dimension#")
SDMX_MEAS = Namespace("http://purl.org/linked-data/sdmx/2009/measure#")
SDMX_CODE = Namespace("http://purl.org/linked-data/sdmx/2009/code#")
SCHEMA = Namespace("https://schema.org/")
PROV = Namespace("http://www.w3.org/ns/prov#")
WD = Namespace("http://www.wikidata.org/entity/")
GN = "https://sws.geonames.org/{}/"

CITY_TYPE = {"City proper": "CityProper", "Urban agglomeration": "UrbanAgglomeration"}
RECORD_TYPE = {
    "Census - de jure - complete tabulation": "CensusDeJureCompleteTabulation",
    "Estimate - de jure": "EstimateDeJure",
}
RELIABILITY = {"Final figure, complete": "FinalFigureComplete", "Provisional figure": "ProvisionalFigure"}


def clean_text(value):
    """Collapse whitespace (the source footnotes contain stray '\\r\\n' and padding)."""
    if pd.isna(value):
        return None
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value or None


def prepare(original_csv: Path) -> pd.DataFrame:
    raw = pd.read_csv(original_csv, dtype=str, keep_default_na=False)

    for col, expected in (("Area", "Total"), ("Sex", "Both Sexes")):
        values = set(raw[col])
        if values != {expected}:
            raise SystemExit(f"Column {col!r} is no longer constant ({values}); update the model")

    cities = pd.read_csv(ROOT / "mappings/city_reconciliation.csv", dtype=str, keep_default_na=False)
    countries = pd.read_csv(ROOT / "mappings/countries.csv", dtype=str, keep_default_na=False)
    unknown = set(raw["City"]) - set(cities["source_name"])
    if unknown:
        raise SystemExit(f"Cities missing from mappings/city_reconciliation.csv: {sorted(unknown)}")

    df = pd.DataFrame({
        "observation_id": [f"observation-{i}" for i in range(1, len(raw) + 1)],
        "reported_country_name": raw["Country or Area"],
        "reported_city_name": raw["City"],
        "city_type": raw["City type"],
        "record_type": raw["Record Type"],
        "reliability": raw["Reliability"],
        "reference_year": raw["Year"].astype(int),
        "source_year": raw["Source Year"].astype(float).astype(int),
        "population": raw["Value"].astype(float).round().astype(int),
        "footnote_text": raw["footnotes"].map(clean_text),
    })
    df = df.merge(cities, how="left", left_on="reported_city_name", right_on="source_name")
    df = df.merge(countries[["source_name", "iso3"]].rename(columns={"source_name": "reported_country_name"}),
                  how="left", on="reported_country_name")
    if (df["iso3"] != df["country_iso3"]).any():
        raise SystemExit("City/country mismatch between the data and the reconciliation table")

    footnotes = {t: f"footnote-{i}" for i, t in
                 enumerate(sorted(df["footnote_text"].dropna().unique()), start=1)}
    df["footnote_id"] = df["footnote_text"].map(footnotes)

    notes = pd.read_csv(ROOT / "mappings/data_quality_notes.csv", dtype=str)
    df = df.merge(notes, how="left", on="observation_id")

    key = ["city_id", "city_type", "record_type", "reference_year"]
    dupes = df[df.duplicated(key, keep=False)]
    if not dupes.empty:
        raise SystemExit(f"Duplicate observations after reconciliation:\n{dupes[key]}")

    return df[[
        "observation_id", "country_iso3", "reported_country_name", "city_id", "canonical_name",
        "reported_city_name", "wikidata_qid", "city_type", "record_type", "reliability",
        "reference_year", "source_year", "population", "footnote_id", "footnote_text", "quality_note",
    ]].rename(columns={"canonical_name": "city_name"})


def build_graph(df: pd.DataFrame, group: str) -> Graph:
    base = f"https://w3id.org/FAIR-course-UT/2026/group{group}/"
    DATA = Namespace(base + "data#")
    ONT = Namespace(base + "ont#")

    g = Graph()
    for prefix, ns in (("data", DATA), ("ont", ONT), ("qb", QB), ("sdmx-dimension", SDMX_DIM),
                       ("sdmx-measure", SDMX_MEAS), ("sdmx-code", SDMX_CODE), ("schema", SCHEMA),
                       ("prov", PROV), ("wd", WD), ("dct", DCTERMS), ("owl", OWL), ("skos", SKOS)):
        g.bind(prefix, ns)

    dataset, dsd = DATA["dataset"], DATA["dsd"]
    g.add((dataset, RDF.type, QB.DataSet))
    g.add((dataset, RDFS.label, Literal("Benelux city population (UNSD), 2000-2023", lang="en")))
    g.add((dataset, QB.structure, dsd))
    g.add((dataset, DCTERMS.conformsTo, URIRef(base + "ont")))
    g.add((dataset, PROV.wasDerivedFrom, URIRef("https://datahub.io/core/population-city")))
    g.add((dataset, DCTERMS.source, URIRef("http://data.un.org/Data.aspx?d=POP&f=tableCode:240")))
    g.add((dataset, DCTERMS.license, URIRef("https://opendatacommons.org/licenses/pddl/1-0/")))
    g.add((dsd, RDF.type, QB.DataStructureDefinition))
    components = [
        ("dimension", ONT.city), ("dimension", ONT.cityType), ("dimension", ONT.recordType),
        ("dimension", SDMX_DIM.refPeriod), ("dimension", SDMX_DIM.sex),
        ("measure", ONT.population), ("attribute", ONT.reliability),
        ("attribute", ONT.sourceYear), ("attribute", ONT.hasFootnote),
    ]
    for order, (kind, prop) in enumerate(components, start=1):
        comp = DATA[f"dsd-component-{order}"]
        g.add((dsd, QB.component, comp))
        g.add((comp, RDF.type, QB.ComponentSpecification))
        g.add((comp, QB[kind], prop))
        g.add((comp, QB.order, Literal(order)))

    
    countries = pd.read_csv(ROOT / "mappings/countries.csv", dtype=str, keep_default_na=False)
    for c in countries.itertuples():
        node = DATA[f"country-{c.iso3}"]
        g.add((node, RDF.type, SCHEMA.Country))
        g.add((node, RDFS.label, Literal(c.label_en, lang="en")))
        if c.source_name != c.label_en:  
            g.add((node, SKOS.altLabel, Literal(c.source_name, lang="en")))
        g.add((node, ONT.iso3166Alpha3, Literal(c.iso3)))
        g.add((node, ONT.m49Code, Literal(c.m49_code)))
        g.add((node, OWL.sameAs, WD[c.wikidata_qid]))
        g.add((node, SKOS.exactMatch, URIRef(GN.format(c.geonames_id))))

    cities = pd.read_csv(ROOT / "mappings/city_reconciliation.csv", dtype=str, keep_default_na=False)
    for c in cities.drop_duplicates("city_id").itertuples():
        node = DATA[f"city-{c.city_id}"]
        g.add((node, RDF.type, ONT.City))
        g.add((node, RDFS.label, Literal(c.canonical_name)))
        for lang, label in (("nl", c.label_nl), ("fr", c.label_fr), ("en", c.label_en)):
            if label:
                g.add((node, SKOS.prefLabel, Literal(label, lang=lang)))
        g.add((node, SCHEMA.containedInPlace, DATA[f"country-{c.country_iso3}"]))
        if c.wikidata_qid:
            g.add((node, OWL.sameAs, WD[c.wikidata_qid]))

    for fid, text in df.dropna(subset=["footnote_id"])[["footnote_id", "footnote_text"]].drop_duplicates().itertuples(index=False):
        g.add((DATA[fid], RDF.type, ONT.Footnote))
        g.add((DATA[fid], RDFS.comment, Literal(text, lang="en")))

    for r in df.itertuples():
        obs = DATA[r.observation_id]
        g.add((obs, RDF.type, ONT.PopulationObservation))
        g.add((obs, QB.dataSet, dataset))
        g.add((obs, ONT.city, DATA[f"city-{r.city_id}"]))
        g.add((obs, ONT.cityType, ONT[CITY_TYPE[r.city_type]]))
        g.add((obs, ONT.recordType, ONT[RECORD_TYPE[r.record_type]]))
        g.add((obs, SDMX_DIM.refPeriod, Literal(str(r.reference_year), datatype=XSD.gYear)))
        g.add((obs, SDMX_DIM.sex, SDMX_CODE["sex-T"]))
        g.add((obs, ONT.population, Literal(int(r.population), datatype=XSD.nonNegativeInteger)))
        g.add((obs, ONT.reliability, ONT[RELIABILITY[r.reliability]]))
        g.add((obs, ONT.sourceYear, Literal(str(r.source_year), datatype=XSD.gYear)))
        g.add((obs, ONT.reportedCityName, Literal(r.reported_city_name)))
        if isinstance(r.footnote_id, str):
            g.add((obs, ONT.hasFootnote, DATA[r.footnote_id]))
        if isinstance(r.quality_note, str):
            g.add((obs, ONT.qualityNote, Literal(r.quality_note, lang="en")))
    return g


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--group", default="NN", help="your group number as registered in Canvas")
    args = parser.parse_args()

    df = prepare(ROOT / "data/original/Benelux_data.csv")
    prepared = ROOT / "data/prepared/benelux_city_population_clean.csv"
    df.to_csv(prepared, index=False)

    g = build_graph(df, args.group)
    out = ROOT / "data/rdf/benelux-city-population.ttl"
    g.serialize(out, format="turtle")
    print(f"{len(df)} rows -> {prepared.relative_to(ROOT)}")
    print(f"{len(g)} triples -> {out.relative_to(ROOT)}")
    print(f"{df.city_id.nunique()} cities, {df.footnote_id.nunique()} footnotes")


if __name__ == "__main__":
    main()
