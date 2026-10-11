"""Generates a deliberately messy customer dataset for the demo."""
import numpy as np
import pandas as pd


def make_sample(seed: int = 7, n: int = 150) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    first = ["Aarav", "Maya", "Liam", "Sofia", "Noah", "Isha", "Emma", "Rohan", "Zoe", "Kabir"]
    last = ["Sharma", "Patel", "Smith", "Garcia", "Brown", "Khan", "Miller", "Rao", "Lee", "Nair"]
    names = [f"{rng.choice(first)} {rng.choice(last)}" for _ in range(n)]
    df = pd.DataFrame({
        "customer_id": np.arange(1001, 1001 + n),
        "name": names,
        "email": [nm.lower().replace(" ", ".") + f"{i}@example.com" for i, nm in enumerate(names)],
        "age": rng.integers(19, 68, n).astype(float),
        "country": rng.choice(["India", "USA", "UK", "Germany", "Canada"], n),
        "signup_date": (pd.Timestamp("2024-01-01") + pd.to_timedelta(rng.integers(0, 300, n), unit="D")).strftime("%Y-%m-%d"),
        "monthly_spend": rng.normal(120, 30, n).round(2),
    })
    pick = lambda k: rng.choice(n, k, replace=False)
    df.loc[pick(8), "country"] = ["india", "  India", "usa", "USA ", "uk", "germany ", "CANADA", " usa"]
    df.loc[pick(4), "email"] = ["john.smith@", "no-at-sign.com", "a@b", "maya@@mail.com"]
    df.loc[pick(6), "age"] = np.nan
    df.loc[pick(5), "monthly_spend"] = np.nan
    df.loc[pick(4), "country"] = np.nan
    df.loc[pick(3), "email"] = np.nan
    df.loc[pick(2), "name"] = np.nan
    df.loc[pick(4), "age"] = [-3, 230, 150, 400]
    df.loc[pick(3), "monthly_spend"] = [9500, 12000, 15000]
    df.loc[pick(4), "signup_date"] = ["not available", "2024-13-45", "31/02/2024", "TBD"]
    df.loc[pick(3), "signup_date"] = ["05/03/2024", "Mar 7 2024", "2024/04/11"]
    dups = df.sample(8, random_state=seed)
    return pd.concat([df, dups]).sample(frac=1, random_state=seed).reset_index(drop=True)


if __name__ == "__main__":
    make_sample().to_csv("sample_data.csv", index=False)
    print("Wrote sample_data.csv")
