"""Fourthwall Connect 0.1 - diagnostic connection only, Python standard library."""
import base64
import json
import queue
import threading
import urllib.error
import urllib.request
from datetime import datetime

BASE = 'https://api.fourthwall.com/open-api/v1.0'
PATHS = ('/shops/current', '/product-templates')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_endpoint(path, username, password, opener=None):
    if path not in PATHS:
        raise ValueError('Endpoint non consentito')
    auth = base64.b64encode((username + ':' + password).encode('utf-8')).decode('ascii')
    request = urllib.request.Request(BASE + path, method='GET', headers={
        'Authorization': 'Basic ' + auth,
        'Accept': 'application/json', 'User-Agent': 'BeyondTheNextConnect/0.6'
    })
    client = opener or urllib.request.build_opener(NoRedirect())
    try:
        with client.open(request, timeout=20) as response:
            payload = response.read(4 * 1024 * 1024 + 1)
            if len(payload) > 4 * 1024 * 1024:
                return {'ok': False, 'message': 'Risposta troppo grande; test incompleto.'}
            data = json.loads(payload)
            if not isinstance(data, (dict, list)):
                return {'ok': False, 'message': 'Formato della risposta inatteso.'}
            if path == '/shops/current' and (not isinstance(data, dict) or not data.get('id')):
                return {'ok': False, 'message': 'Risposta ricevuta, ma negozio non identificato.'}
            return {'ok': True, 'message': 'Accesso riuscito.'}
    except urllib.error.HTTPError as error:
        messages = {
            401: 'Credenziali non accettate: controlla username e password API.',
            403: 'Accesso negato: verifica i permessi dell\'utente API.',
            404: 'Funzione non disponibile a questo indirizzo API.',
            429: 'Limite di richieste raggiunto: riprova piu tardi.'
        }
        return {'ok': False, 'message': messages.get(error.code, 'Risposta HTTP ' + str(error.code) + '. Riprova piu tardi.')}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {'ok': False, 'message': 'Connessione non riuscita: verifica Internet e riprova.'}
    except (ValueError, UnicodeError):
        return {'ok': False, 'message': 'Il servizio ha restituito una risposta non valida.'}


def check_connection(username, password, reader=read_endpoint):
    shop = reader(PATHS[0], username, password)
    report = ['Fourthwall Connect 0.1', datetime.now().isoformat(timespec='seconds'),
              'Negozio: ' + shop['message']]
    if shop['ok']:
        catalog = reader(PATHS[1], username, password)
        report.append('Modelli prodotto: ' + catalog['message'])
    else:
        report.append('Modelli prodotto: non verificati.')
    report.extend(['', 'Test di sola lettura. Nessun prodotto creato o pubblicato.',
                   'La scrittura e la pubblicazione NON sono state verificate.',
                   'Questa app non collega il negozio alla chat e non automatizza ancora le vendite.'])
    return shop['ok'], '\n'.join(report)


def main():
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title('Fourthwall - Collega il tuo negozio')
    root.geometry('740x610')
    root.minsize(660, 570)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Collega il tuo negozio', font=('Segoe UI', 21, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='Primo passo: verifica delle credenziali Fourthwall.',
              font=('Segoe UI', 11)).pack(anchor='w', pady=(8, 16))
    ttk.Label(frame, text='Inserisci i dati creati in Settings > For Developers > Open API.\n'
              'Sono inviati soltanto a Fourthwall, tramite HTTPS. Non vengono salvati.').pack(anchor='w')
    ttk.Label(frame, text='Username API').pack(anchor='w', pady=(16, 4))
    username = ttk.Entry(frame, show='*')
    username.pack(fill='x')
    ttk.Label(frame, text='Password API').pack(anchor='w', pady=(12, 4))
    password = ttk.Entry(frame, show='*')
    password.pack(fill='x')
    status = tk.StringVar(value='Non collegato')
    ttk.Label(frame, textvariable=status).pack(anchor='w', pady=(14, 4))
    actions = ttk.Frame(frame)
    actions.pack(fill='x', pady=(4, 12))
    results = queue.Queue()
    output = tk.Text(frame, wrap='word', height=11, font=('Segoe UI', 10), state='disabled')
    output.pack(fill='both', expand=True)
    last_report = ['']

    def render(text):
        output.configure(state='normal')
        output.delete('1.0', 'end')
        output.insert('1.0', text)
        output.configure(state='disabled')

    def worker(user, secret):
        try:
            results.put(check_connection(user, secret))
        except Exception:
            # Never display exception bodies, headers, or server payloads containing secrets.
            results.put((False, 'Errore imprevisto durante il test. Nessuna modifica effettuata.'))

    def start():
        user, secret = username.get().strip(), password.get()
        if not user or not secret:
            status.set('Inserisci entrambi i campi.')
            return
        if ':' in user or any(c in user + secret for c in '\r\n'):
            status.set('Credenziali non valide: verifica che non contengano ritorni a capo.')
            return
        test.configure(state='disabled')
        copy.configure(state='disabled')
        last_report[0] = ''
        status.set('Verifica in corso, massimo circa 40 secondi...')
        render('Contatto Fourthwall...')
        username.delete(0, 'end')
        password.delete(0, 'end')
        threading.Thread(target=worker, args=(user, secret), daemon=True).start()

    def poll():
        try:
            ok, report = results.get_nowait()
            status.set('Credenziali verificate - leggi il risultato sotto.' if ok else 'Collegamento non riuscito.')
            last_report[0] = report
            render(report)
            test.configure(state='normal')
            copy.configure(state='normal')
        except queue.Empty:
            pass
        root.after(150, poll)

    def copy_report():
        root.clipboard_clear()
        root.clipboard_append(last_report[0])
        status.set('Esito copiato, senza credenziali: puoi incollarlo in chat.')

    test = ttk.Button(actions, text='Verifica collegamento', command=start)
    test.pack(side='left')
    copy = ttk.Button(actions, text='Copia esito senza credenziali', command=copy_report, state='disabled')
    copy.pack(side='left', padx=12)
    render('Questa prima versione verifica accesso al negozio e disponibilita dei modelli.\n\n'
           'Non pubblica, non compra e non modifica il negozio.\n'
           'Non salva credenziali, non installa servizi e non si avvia con Windows.')
    root.after(150, poll)
    username.focus()
    root.mainloop()


if __name__ == '__main__':
    main()
