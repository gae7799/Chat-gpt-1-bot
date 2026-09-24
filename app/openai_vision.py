"""OpenAI vision connection and structured artistic analysis."""
import base64
import json
import mimetypes
from pathlib import Path
from urllib import error, request

from connessione import Vault
from consiglio_agenti import schema as council_schema, instructions as council_instructions, validate as validate_council

OPENAI_TARGET = 'BotFoto/OpenAI/API'
MODEL = 'gpt-5.6-terra'
API = 'https://api.openai.com/v1'
MAX_IMAGE_BYTES = 20 * 1024 * 1024


class OpenAIError(RuntimeError):
    """Only fixed, non-sensitive diagnostic text may be passed here."""


def http_diagnostic(status, detail):
    messages = {400:'Richiesta OpenAI non accettata',401:'Chiave OpenAI non valida',
                403:'Permessi OpenAI insufficienti',404:'Modello non disponibile per questa chiave',
                429:'Limite o credito OpenAI raggiunto'}
    reason = messages.get(status, 'Errore del servizio OpenAI') + f' (HTTP {status}).'
    code = detail.get('code') if isinstance(detail, dict) else None
    if code == 'insufficient_quota': reason += ' Credito o quota API esauriti: controlla la fatturazione API.'
    elif code == 'rate_limit_exceeded': reason += ' Troppe richieste: attendi prima di riprovare.'
    elif code == 'model_not_found': reason += ' Il modello configurato non è accessibile.'
    elif code in ('unsupported_parameter','unsupported_value','invalid_value'):
        reason += ' Un parametro non è supportato o ha un valore non valido.'
    parameter = detail.get('param') if isinstance(detail,dict) else None
    if parameter in ('model','tools','tools[0].type','tools[0].search_context_size','tool_choice',
                     'max_tool_calls','max_output_tokens','include','store','reasoning.effort'):
        reason += ' Parametro: '+parameter+'.'
    return reason


class OpenAIVault(Vault):
    def __init__(self):
        super().__init__(OPENAI_TARGET)


def _call(path, key, payload=None, method='GET', timeout=60):
    headers = {'Authorization': 'Bearer ' + key, 'Accept': 'application/json',
               'User-Agent': 'BeyondTheNextStoreManager/1.1'}
    data = None
    if payload is not None:
        data = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read(4 * 1024 * 1024)
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        try:
            detail = json.loads(exc.read(65536)).get('error',{})
        except (ValueError,AttributeError,OSError): detail = {}
        raise OpenAIError(http_diagnostic(exc.code, detail)) from None
    except (error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        raise OpenAIError('Connessione a OpenAI non riuscita o tempo di attesa scaduto.') from None


def verify_key(key, caller=_call):
    if not isinstance(key, str) or not key.startswith('sk-') or any(c in key for c in '\r\n\x00'):
        return False, 'Inserisci una chiave API OpenAI valida.'
    caller('/models/' + MODEL, key)
    return True, f'OpenAI collegato. Modello: {MODEL}. Chiave protetta sul PC.'


def final_parts(response):
    if not isinstance(response,dict): raise OpenAIError('Risposta OpenAI non leggibile.')
    if response.get('status') == 'incomplete':
        detail = response.get('incomplete_details') or {}
        if detail.get('reason') == 'max_output_tokens':
            raise OpenAIError('Risposta incompleta: limite di token raggiunto prima della conclusione.')
        raise OpenAIError('Risposta OpenAI incompleta; nessun risultato finale disponibile.')
    if response.get('status') in ('failed','cancelled'):
        raise OpenAIError('Richiesta OpenAI fallita o annullata.')
    messages = [item for item in response.get('output',[]) if item.get('type')=='message' and item.get('phase')!='commentary']
    for item in reversed(messages):
        parts = [c for c in item.get('content',[]) if c.get('type')=='output_text' and isinstance(c.get('text'),str)]
        if parts: return parts
    raise OpenAIError('OpenAI non ha restituito una risposta finale leggibile.')


def _output_text(response):
    return '\n'.join(part['text'] for part in final_parts(response))


def analyze_photo(path, key, caller=_call):
    path = Path(path)
    if not path.is_file() or path.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
        raise RuntimeError('La fotografia deve essere JPG o PNG.')
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise RuntimeError('Fotografia oltre 20 MB: riducila prima dell’analisi.')
    mime = 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg'
    image_url = f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
    schema = {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'title': {'type': 'string', 'minLength': 2, 'maxLength': 80},
            'description': {'type': 'string', 'minLength': 20, 'maxLength': 500},
            'theme': {'type': 'string', 'minLength': 2, 'maxLength': 80},
            'score': {'type': 'integer', 'minimum': 0, 'maximum': 100},
            'recommended': {'type': 'boolean'},
            'reason': {'type': 'string', 'minLength': 10, 'maxLength': 300},
            'consiglio': council_schema(),
        },
        'required': ['title', 'description', 'theme', 'score', 'recommended', 'reason', 'consiglio']
    }
    prompt = (
        'Agisci come direttore artistico e commerciale del negozio fotografico Beyond The Next. '
        'Valuta composizione, forza visiva, coerenza con fotografia manipolata, palette intensa, ombre, '
        'paesaggio, identità e principio less is more. Crea un titolo italiano professionale, una '
        'descrizione elegante senza citare nome o cognome dell’autore, un tema, un punteggio e stabilisci '
        'se l’opera è abbastanza forte per essere proposta come stampa. Non identificare persone reali. '
        + council_instructions()
    )
    payload = {
        'model': MODEL,
        'input': [{'role': 'user', 'content': [
            {'type': 'input_text', 'text': prompt},
            {'type': 'input_image', 'image_url': image_url, 'detail': 'auto'}]}],
        'max_output_tokens': 1800,
        'text': {'format': {'type': 'json_schema', 'name': 'photo_analysis', 'strict': True, 'schema': schema}}
    }
    try:
        result = json.loads(_output_text(caller('/responses', key, payload, 'POST', 120)))
    except json.JSONDecodeError:
        raise RuntimeError('Risposta AI incompleta: nessuna opera è stata selezionata.') from None
    if not isinstance(result, dict) or any(name not in result for name in schema['required']):
        raise RuntimeError('Analisi OpenAI incompleta.')
    result = validate_council(result)
    result['title'] = result['title'].strip()[:80]
    result['description'] = result['description'].strip()[:500]
    result['theme'] = result['theme'].strip()[:80]
    result['reason'] = result['reason'].strip()[:300]
    return result


def open_setup(parent):
    import tkinter as tk
    from tkinter import ttk, messagebox
    win = tk.Toplevel(parent)
    win.title('Collega OpenAI')
    win.geometry('620x330')
    body = ttk.Frame(win, padding=18); body.pack(fill='both', expand=True)
    ttk.Label(body, text='Intelligenza visiva OpenAI', font=('Segoe UI', 17, 'bold')).pack(anchor='w')
    state = tk.StringVar(value='La chiave API è separata dall’abbonamento ChatGPT e resta sul tuo PC.')
    ttk.Label(body, textvariable=state, wraplength=570).pack(anchor='w', pady=(4, 12))
    ttk.Label(body, text='Chiave API OpenAI').pack(anchor='w')
    secret = ttk.Entry(body, show='*'); secret.pack(fill='x', pady=(3, 10))

    def save():
        key = secret.get().strip()
        try:
            ok, message = verify_key(key)
            if not ok:
                messagebox.showerror('Chiave', message, parent=win); return
            OpenAIVault().save('openai', key)
            secret.delete(0, 'end'); state.set(message)
            messagebox.showinfo('OpenAI', message, parent=win)
        except Exception as exc:
            messagebox.showerror('OpenAI', str(exc), parent=win)

    def forget():
        try:
            OpenAIVault().delete(); state.set('Chiave OpenAI rimossa dal PC.')
        except Exception as exc:
            messagebox.showerror('OpenAI', str(exc), parent=win)

    actions = ttk.Frame(body); actions.pack(anchor='w')
    ttk.Button(actions, text='Verifica e salva', command=save).pack(side='left')
    ttk.Button(actions, text='Rimuovi chiave', command=forget).pack(side='left', padx=8)
    ttk.Label(body, text='Limite del bot: massimo 5 nuove analisi al giorno. Pubblicità: 0 €.',
              font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(18, 0))
