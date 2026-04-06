# LLM-NetConf-E4 — Assistant de configuration réseau fondé sur les LLM

## Projet E4 D8 — ESIEE Paris 2026
Encadrants : Mme Ting Wang & M. Fen Zhou (POSTECH)

## Description
Basé sur le papier IEEE GAIN 2024 : S-Witch (Switch Configuration Assistant with LLM and Prompt Engineering).

Ce projet implémente un assistant capable de générer automatiquement des commandes CLI Cisco à partir de requêtes en langage naturel, en utilisant GNS3 comme Digital Twin.

## Architecture
- **API FastAPI** : Serveur LLM (port 8000)
- **LangChain + Groq** : Chains v4 et v5 adaptées
- **GNS3** : Digital Twin réseau (port 3080)
- **Web UI Angular** : Interface chat

## Installation
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Lancer le serveur
```bash
python -m api.app.server
```

## Demo complète GNS3
```bash
python full_demo.py
```

## Auteurs
Melissa Tefit, Grégoire Bouet, Fatima Tidaoui, Hafiz Khizar, Rana Khizar
