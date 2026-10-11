# Steady: Daily Mood Tracker with Biometric Alarms

A prototype AI-product concept that tracks daily mood and raises an alarm when mood drops or when body signals (pulse, breathing rate, HRV) suggest anger or rising stress.

> **Status:** Prototype. Body signals are **simulated**. This is not a medical device.

## The problem

People often notice stress or anger only after it has escalated. Mood journals are retrospective, and wearables show raw numbers without telling you when to act. Steady closes that gap by combining a daily self-report with live physiological signals and interrupting the user at the right moment.

## Features

- **Live body signals:** pulse (bpm), breaths per minute and HRV (ms), shown with a breathing orb that moves at the user's breathing rate and changes color with state.
- **Anger and stress alarm:** an arousal score is compared with a resting baseline. When it stays high, a banner appears with a three-tone alarm and device vibration.
- **Mood-drop alarm:** fires when mood falls 2 or more points between check-ins, or declines three check-ins in a row.
- **Guided breathing:** 4-second inhale, 6-second exhale, started from the alarm banner.
- **Daily check-in:** 1 to 5 mood rating with an optional note.
- **History:** mood trend chart, recent check-ins and alarm log, stored locally in the browser (`localStorage`).
- **Scenario simulator:** Calm, Walking, Stressed and Angry buttons for demoing without a sensor.
- Dark mode, sound toggle, reduced-motion support, keyboard focus styles.

## How detection works

Baseline (resting): pulse 68 bpm, breathing 14/min, HRV 55 ms.

```
pulse_score  = clamp((pulse - 68) / 30, 0, 1.5)
breath_score = clamp((breaths - 14) / 10, 0, 1.5)
hrv_score    = clamp((55 - hrv) / 35, 0, 1.5)

arousal = (pulse_score + breath_score + hrv_score) / 3
```

| Arousal | Duration | Result |
|---|---|---|
| >= 0.5 | 8 seconds | "Tension is building" (amber alert) |
| >= 0.85 | 4 seconds | "Anger detected" (red alarm) |

Alerts have a 30-second cooldown after dismissal. Walking raises pulse but stays below the threshold, which keeps exercise from triggering false alarms.

## Run it

No build step or dependencies.

1. Download or clone this repository.
2. Open `index.html` in a browser.

To host it with GitHub Pages: **Settings > Pages > Deploy from branch > `main` / root**.

## Project structure

```
steady-mood-tracker/
├── index.html   # Entire app (HTML, CSS, JS in one file)
└── README.md
```

## Limitations

- Sensor data is simulated. Browsers cannot read pulse or breathing directly.
- Thresholds are placeholders and are not calibrated to individuals or clinically validated.
- Data is stored only in the user's browser.
- Not a medical device and not a substitute for professional care.

## Roadmap

- [ ] Real sensor input (Web Bluetooth heart-rate, HealthKit, Health Connect)
- [ ] Per-user baseline calibration
- [ ] Separate anger from exercise and caffeine using motion and context
- [ ] Push notifications
- [ ] Trusted-contact escalation and crisis resources for sustained low mood
- [ ] Weekly insights and trigger patterns

## Product notes (PM view)

**Target users:** people managing stress or anger, and people tracking mood for therapy.

**Proposed success metrics**
- Alarm precision: share of alarms the user marks as "useful"
- Dismissal rate and time-to-dismiss
- Guided-breathing completion rate
- Check-in streak length and 30-day retention
- False-alarm rate during exercise

**Key risks:** false alarms causing alert fatigue, biometric privacy, and over-reliance on the app during real distress.

## License

MIT (add a `LICENSE` file if you want to publish under this license).
