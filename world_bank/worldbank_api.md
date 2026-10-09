Here are some examples (the HTTP responses are not shown for brevity):

Python client¶
The Web API can be called by the Python client available here: https://pypi.org/project/dbnomics/ (source code).

Install the package in a new virtual environment:


python3 -m venv test-dbnomics-python
source test-dbnomics-python/bin/activate
pip install dbnomics
python

Web API: Clone with https: https://git.nomics.world/dbnomics/dbnomics-api.git


DBnomics API
 22.1.17 
[ Base URL: /v22 ]
/v22/apispec_1.json
This is the documentation of DBnomics Web API.
Each endpoint is listed below, and if you click on it you will see its parameters.
It's also possible to try these endpoints directly from this page by setting parameters values in a web form.

Requests examples
Get one series
http://api.db.nomics.world/v22/series/ECB/RTD/A.S0.N.F_CEC_CGG_D0.F

... and the same with series values:

http://api.db.nomics.world/v22/series/ECB/RTD/A.S0.N.F_CEC_CGG_D0.F?observations=true

default

GET
​/datasets​/{provider_code}
Respond one or several datasets of a provider.
get_datasets__provider_code_
GET
​/datasets​/{provider_code}​/{dataset_code}
Respond one or several datasets of a provider.
get_datasets__provider_code___dataset_code_
GET
​/last-updates
Respond a list of providers and a list of datasets sorted by creation/conversion date, most recent first.
get_last_updates
GET
​/providers
Respond a list of providers.
get_providers
GET
​/providers​/{provider_code}
Respond a provider with its category tree.
get_providers__provider_code_
GET
​/search
Respond a list of datasets from a full-text search.
get_search
GET
​/series
Respond a list of series found by IDs, belonging potentially to different providers and datasets.
get_series
GET
​/series​/{provider_code}​/{dataset_code}
Respond a list of series belonging to the same dataset.
get_series__provider_code___dataset_code_
GET
​/series​/{provider_code}​/{dataset_code}​/{series_code}
Respond a list of series belonging to the same dataset.
get_series__provider_code___dataset_code___series_code_








# Fetch provider metadata
curl "https://api.db.nomics.world/v22/providers/INSEE"

# Fetch dataset metadata
curl "https://api.db.nomics.world/v22/datasets/INSEE/IPC-2015"

# Fetch series metadata
curl "https://api.db.nomics.world/v22/series/INSEE/IPC-2015/A.IPC.SO.00.00.INDICE.ENSEMBLE.FE.SO.BRUT.2015.FALSE"

# Fetch series metadata with observations
curl "https://api.db.nomics.world/v22/series/INSEE/IPC-2015/A.IPC.SO.00.00.INDICE.ENSEMBLE.FE.SO.BRUT.2015.FALSE?observations=1"
Python client¶
The Web API can be called by the Python client available here: https://pypi.org/project/dbnomics/ (source code).

Install the package in a new virtual environment:


Downloading a series¶

from dbnomics import fetch_series

fetch_series("INSEE/IPC-2015/A.IPC.SO.00.00.INDICE.ENSEMBLE.FE.SO.BRUT.2015.FALSE")
The fetch_series function returns a Pandas DataFrame with the "period" and "value" columns (among others).

Downloading a whole dataset¶
On the website, the "Download" button is only enabled for up to 1000 series at once, after filters are applied (see Download series). With the Web API and its clients, you can download more time series directly from your preferred environment.

To download all the series of a dataset, pass the provider code and the dataset code to fetch_series, and set the max_nb_series parameter to the maximum number of series you are willing to download:


from dbnomics import fetch_series

df = fetch_series("IMF", "GFSCOFOG", max_nb_series=300_000)
max_nb_series is required to download a whole dataset: without it, only 50 series are returned by default, and the client raises an error if the dataset contains more series.

Downloading a whole dataset can be slow. If you don't need all the series, it is better to apply a dimension filter first (see below).

Filtering by dimensions¶
Instead of downloading a whole dataset, you can restrict the download to the series you are interested in, using the dimensions parameter. It takes a dict mapping dimension codes to the lists of value codes you want to keep.

For example, to download all the series of the IMF GFSCOFOG dataset for Bolivia:


from dbnomics import fetch_series

df = fetch_series("IMF", "GFSCOFOG", dimensions={"REF_AREA": ["BO"]}, max_nb_series=2000)
The dimension columns are included in the DataFrame, so you can further filter the result after downloading it.

Full tutorial¶
Have a look at the tutorial notebook for more examples.

Other clients¶
Other clients for the Web API are made available by the community.

Clients for programming languages:

R: rdbnomics (source code)
Julia: DBnomics.jl
Stata: dbnomics
Clients for external software:

EViews: foreign format database
Gretl: dbnomics addon
Matlab: mdbnomicsData model¶
This page gives a high-level overview of the DBnomics data model, and the main design principles behind it.

The data model page of the documentation of the dbnomics-toolbox library explains how this data model is implemented in Python and how to use it in fetchers.

Data representation principles¶
DBnomics distinguishes data from its format, and simplifies format only.

This means DBnomics tries to preserve provider semantics while normalizing a limited set of representation details needed for consistent access across providers.

Preserved provider semantics¶
The following items are kept as-is from the provider:

time series and their observations
dataset dimensions: a dataset may have a dimension named "Country" with values "France", "Germany", etc., and another dataset may have a dimension named "REF_AREA" with values "FR", "DE", etc. DBnomics does not try to harmonize those dimensions, but keeps them as-is from the provider.
NA (non-available) values usage: DBnomics does not add or remove them. If a provider distributes a time series with an incomplete calendar (with some missing periods), DBnomics does not try to complete it
Some providers distribute time series with no observation, or with only NA values, and DBnomics keeps them as-is as well. Here are some examples:

time series with no observation
time series with only NA values
other special cases on our wiki
Normalized representation¶
Some data is normalized from provider source data:

periods: providers use different ways to represent them and DBnomics defines a standard format (e.g. 202001 or 2020M01 becomes 2020-01)
NA (non-available) values: some providers use NaN, some others -9999, etc. DBnomics always uses NA
Normalization is done by each fetcher in the data conversion part, based on the knowledge of the provider source data. For example, a period like 2000-qII would be normalized as 2000-Q2.

Why normalize this?

If we kept the original formats for periods or NA values, it would be difficult to, for example, represent time series on a chart, because each format would have to be handled separately.

The best place to do this normalization is in the fetcher, because it has the knowledge of the provider source data, and can be adapted to each provider.

Conceptual model¶
We first present a conceptual model of the main DBnomics concepts and their relationships:

has many

has many

has many

Provider

Dataset

Series

Observation

Note

This diagram is a conceptual model, meant as a mental model of the main DBnomics concepts and their relationships.

It does not reflect the actual implementation or describe the in-memory representation used by DBnomics or by dbnomics_toolbox.model. The subsections below describe the conceptual model.

Provider¶
Each provider has:

a code that must be unique across providers
many datasets (see section below)
Examples: IMF for International Monetary Fund, OECD for Organisation for Economic Co-operation and Development, WB for World Bank, etc.

Provider codes are used in several DBnomics URLs.

Dataset¶
Each dataset is part of a provider and has:

a code that must be unique across a single provider (e.g. BOP for Balance of Payments).
an ID that is the concatenation of the provider code and the dataset code, separated by a slash (e.g. IMF/BOP).
many dimensions definitions (see section below)
many series (see section below)
Dataset codes are used in several DBnomics URLs.

Dataset dimensions¶
In DBnomics datasets are multi-dimensional and are sometimes referred to as data cubes.

Each dataset defines an ordered list of dimensions, and each series of the dataset has a value for each dimension.

For example, a dataset may have dimensions FREQ (frequency), REF_AREA (reference area), UNIT (unit of measurement), etc., and a series of this dataset may have values A for FREQ, FR for REF_AREA, USD for UNIT, etc.

Dataset releases¶
Sometimes providers publish datasets with releases.

In DBnomics each dataset release is a regular dataset having a code following this pattern: {dataset_code}:{release_code}.

For example, IMF publishes WEO every 6 months (e.g. 2019-04, 2019-10, 2020-04, etc.) and DBnomics datasets have the codes WEO:2019-04, WEO:2019-10, WEO:2020-04, etc.

See also: dataset releases.

Series¶
Each series is part of a dataset and has:

a code that must be unique across a single dataset (e.g. A.1C_355.BACK_BP6_USD)
an ID that is the concatenation of the dataset ID and the series code, separated by a slash (e.g. IMF/BOP/A.1C_355.BACK_BP6_USD)
a name that SHOULD be unique
a value for each dimension of the dataset (e.g. FREQ => A, REF_AREA => FR, etc.)
many observations (see section below)
Duplicate series names

Some providers give the same names to many series. DBnomics data model tolerates this, even if it's not recommended.

In this case, the user will always be able to distinguish those time series by looking at their code or dimensions.

Series without code

Some providers don't give codes to series, but only dimensions (e.g. {"FREQ": "A", "REF_AREA": "FR"}). In this case, as the series code is required in the data model of DBnomics, it can be generated from the dimensions (e.g. A.FR).

This does not mean that the series codes must be generated from dimensions: some providers give arbitrary codes to series, that do not correspond to dimensions (e.g. SERIES_137).

However, building the series codes from dimensions is a common practice among providers, and is recommended as it makes them easier to understand and more stable over time.

Observation¶
An observation is a pair of period and value, like {"period": "2020-01", "value": 123.45}.

It can also have attributes: a set of key-value pairs (e.g. {"unit": "USD", "status": "final"}).

Periods can be years (2020), months (2020-01), quarters (2020-Q1), etc. For more information, see the documentation of dbnomics-toolbox on periods.

Example: multi-dimensional dataset¶
A multi-dimensional dataset defines many dimensions and has many series where each one is categorized using dimensions.

To help understanding that concept, here is an example. Let's start from the following hypothetical CSV file named product_prices.csv that tracks the evolution of the price of different products in different countries:

sku	country	year	price
111	FR	2000	12
111	FR	2001	13
111	FR	2002	11
111	DE	2001	9
111	DE	2002	11
111	DE	2003	14
222	FR	2000	87
222	FR	2001	88
222	FR	2002	90
222	FR	2003	79
We can consider this file a multi-dimensional dataset if we identify dimensions in it, and series where each one is categorized by those dimensions.

Based on the given columns, we can infer 2 dimensions: SKU and COUNTRY (we'll keep this order), with values SKU={111,222} and COUNTRY={DE,FR}.

The remaining columns year and price define the observations of each series, and the series can be found by applying a "group-by" operation on the dimensions.

So the dataset is composed of 4 time series, each being related to a single product and country.

Series 111.FR:

period	value
2000	12
2001	13
2002	11
Series 111.DE:

period	value
2001	9
2002	11
2003	14
Series 222.FR:

period	value
2000	87
2001	88
2002	90
2003	79
Series codes

Because the dimensions of a dataset are ordered, we can infer the series codes by concatenating the codes of the values of the dimensions, separated by a . character.

For example, the series for SKU=111 and COUNTRY=FR has the code 111.FR, and not FR.111.

Made with Material for MkDocs

Core design principles¶
Redistribute data as-is¶
DBnomics redistributes data from providers without modifying it. Only the format of the data may be normalized to ensure consistency across different providers. The original dataset and series codes are preserved, numerical values are never modified, and NA (not available) values are kept. The category tree of datasets is also kept as-is, when published by the provider.

The concrete rules about what is preserved as-is and what is normalized are documented on the Data model page.

Automatic data updates¶
We want up-to-date data on DBnomics, so data is updated automatically.

Data acquisition is done by the fetchers which are run automatically by the fetcher pipeline.

We also want to track fetcher executions, which is why we have a dashboard.

Provider data versioning¶
DBnomics is designed to store each revision of the data fetched from a provider when running a fetcher from the pipeline.

As a consequence, past revisions of time series remain accessible. This enables reproducible research for your project.

Access data from work environment¶
DBnomics is designed to allow consumers to download time series directly from their work environment, by exposing data using the data types they are familiar with without having to parse file formats (e.g. XML, CSV, Excel) or copy-paste data by hand.

Read more about the clients of the Web API.

Downloading a whole dataset¶
On the website, the "Download" button is only enabled for up to 1000 series at once, after filters are applied (see Download series). With the Web API and its clients, you can download more time series directly from your preferred environment.

To download all the series of a dataset, pass the provider code and the dataset code to fetch_series, and set the max_nb_series parameter to the maximum number of series you are willing to download:


from dbnomics import fetch_series

df = fetch_series("IMF", "GFSCOFOG", max_nb_series=300_000)
max_nb_series is required to download a whole dataset: without it, only 50 series are returned by default, and the client raises an error if the dataset contains more series.

Downloading a whole dataset can be slow. If you don't need all the series, it is better to apply a dimension filter first (see below).

Filtering by dimensions¶
Instead of downloading a whole dataset, you can restrict the download to the series you are interested in, using the dimensions parameter. It takes a dict mapping dimension codes to the lists of value codes you want to keep.

For example, to download all the series of the IMF GFSCOFOG dataset for Bolivia:


from dbnomics import fetch_series

df = fetch_series("IMF", "GFSCOFOG", dimensions={"REF_AREA": ["BO"]}, max_nb_series=2000)
The dimension columns are included in the DataFrame, so you can further filter the result after downloading it.

Full tutorial¶
Have a look at the tutorial notebook for more examples.

Other clients¶
Other clients for the Web API are made available by the community.

Clients for programming languages:

R: rdbnomics (source code)
Julia: DBnomics.jl
Stata: dbnomics
Clients for external software:

EViews: foreign format database
Gretl: dbnomics addon
Matlab: mdbnomics
Contributing¶
If you're using a programming language or an application that is not already supported, please tell us about it!

To download DBnomics data, you can always call the Web API directly by using the common HTTP functions, but manipulating a dedicated client should feel easier.

You can contribute by telling us how you access DBnomics data from your preferred application.

You can also contribute by writing a new package for a programming language, allowing others to retrieve DBnomics data from that language and helping the DBnomics community grow.

More ways to contribute are described on the contributing page.

Features¶
Time series alignment¶
In order to represent many time series on the same table, they must share a common list of periods.

But sometimes, series distributed by providers are incomplete, like this:

Series A

PERIOD	VALUE
2000	1
2001	7
2003	2
2004	NA
Series B

PERIOD	VALUE
2001	5
2003	6
2004	NA
2005	8
Time series alignment consists of unifying the periods of all requested series, and filling the gaps with NA values:

PERIOD	Series A	Series B
2000	1	NA
2001	7	5
2002	NA	NA
2003	2	6
2004	NA	NA
2005	NA	8
The Web API, via its parameter align_periods, is able to do that:

original non-aligned time series
aligned time series
Note: the difference between both URLs is the usage of the align_periods parameter.

Dataset releases¶
As described in the data model, datasets can have releases in DBnomics.

The Web API is able to resolve the reserved release code latest to the actual release code.

For example, if a dataset has 2 releases WEO:2019-04 and WEO:2019-10, declared in this order, WEO:latest is resolved to WEO:2019-10.

The endpoints of the Web API that accept a dataset code parameter are able to do this resolution using an HTTP temporary redirection (code 302).

For example:


curl -I "https://api.db.nomics.world/v22/datasets/IMF/WEO:latest"

HTTP/1.0 302 FOUND
Location: https://api.db.nomics.world/v22/datasets/IMF/WEO:2019-10
[...]
Made with Material for MkDocs
