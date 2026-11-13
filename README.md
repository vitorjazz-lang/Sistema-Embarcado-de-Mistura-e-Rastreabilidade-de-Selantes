# ⚙️ Máquina Automatizada de Mistura e Rastreabilidade de Selantes

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-4B-C51A4A?logo=raspberrypi&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-Vis%C3%A3o%20Computacional-5C3EE8?logo=opencv&logoColor=white)

**Sistema industrial embarcado em Raspberry Pi 4B para reconhecimento óptico, parametrização automática, homogeneização eletropneumática e rastreabilidade térmica de selantes.**

O projeto consiste em uma **estação automatizada de mistura de selantes industriais (mixer)** desenvolvida para substituir processos manuais por uma operação inteligente, segura e rastreável. Através de visão computacional, o sistema lê o código/rótulo do cartucho, consulta a receita técnica em banco de dados local (`database.json` / `codes.json`), configura automaticamente a rotação e os ciclos pneumáticos e, ao término, imprime uma etiqueta térmica com dados de lote, validade (*work life*) e condições ambientais.

---

## 🎯 Objetivos do Projeto

* Automatizar a identificação de diferentes modelos de selantes industriais (ex.: MC 780, PR 2050, PR 1422, SelaFlex) via câmera USB.
* Controlar com precisão a rotação (motor de passo com driver DM542 a $110 \pm 10\text{ RPM}$) e os cursos verticais (*strokes* via cilindro pneumático e válvula 5/2 vias duplo solenoide).
* Monitorar temperatura e umidade da câmara de batimento em tempo real para garantir conformidade com especificações técnicas de cura.
* Gerar logs imutáveis (`.jsonl` / `.csv`) e emitir etiquetas de rastreabilidade diretamente em impressora térmica Zebra via comandos ZPL II.

---

## 🛠️ Tecnologias e Hardware Utilizados

### Software
* **Python 3.x** – Lógica central de controle concorrente (*multithreading*) e CLP embarcado
* **OpenCV & PyZbar** – Visão computacional e leitura de QR Codes / códigos de barras
* **Tkinter** – Interface Homem-Máquina (IHM) otimizada para display Touchscreen 7" (`800x480`)
* **RPi.GPIO / gpiozero** – Acionamento digital de relés e pulsos `PUL/DIR` do motor de passo
* **ZPL II (Zebra Programming Language)** – Comunicação direta via USB (`/dev/usb/lp0`) para impressão térmica

### Hardware
* **Raspberry Pi 4 Model B** + Terminal Breakout Shield HAT
* **Driver DM542 + Motor de Passo Industrial** (atuador rotativo)
* **Cilindro Pneumático ISO Dupla Ação + Válvula 5/2 Duplo Solenoide 24V** (atuador vertical)
* **Sensor Ambiental DHT22 / SHT3x** (temperatura e umidade)
* **Impressora Térmica Industrial Zebra & Câmera USB Industrial**

---

## 🚀 Como Executar o Projeto

### Pré-requisitos
* Raspberry Pi OS (Linux) com Python 3.8+ e acesso aos barramentos GPIO/USB.

### Passo a passo

1. **Clone este repositório:**
   ```bash
   git clone https://github.com/vitorjazz-lang/Sistema-Embarcado-de-Mistura-e-Rastreabilidade-de-Selantes.git
   cd maquina-selante-automacao
   ```

2. **Crie e ative um ambiente virtual:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Instale as dependências:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure o banco de receitas e execute:**
   Certifique-se de que o arquivo `database.json` esteja na raiz do projeto e execute:
   ```bash
   python main.py
   ```

---

## 🤝 Contribuição

Contribuições, sugestões de melhorias na arquitetura de controle ou novos layouts ZPL são muito bem-vindos! Sinta-se à vontade para abrir uma *Issue* ou enviar um *Pull Request*.
