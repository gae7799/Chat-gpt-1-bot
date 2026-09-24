"""Narrow Fourthwall API client for hidden design drafts. Python stdlib only."""
import base64, json, mimetypes, struct
from pathlib import Path
from urllib import error, parse, request

BASE = 'https://api.fourthwall.com/open-api/v1.0'
MAX_JSON = 4 * 1024 * 1024

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None

class ApiError(RuntimeError): pass

def _auth(user, password):
    return 'Basic ' + base64.b64encode((user + ':' + password).encode()).decode('ascii')

def _json_call(method, path, user=None, password=None, payload=None, public=False):
    if not path.startswith('/') or '://' in path: raise ApiError('Percorso API non valido.')
    headers = {'Accept':'application/json','User-Agent':'BeyondTheNextStoreManager/0.6'}
    if not public: headers['Authorization'] = _auth(user, password)
    data = None
    if payload is not None:
        data = json.dumps(payload,separators=(',',':')).encode()
        headers['Content-Type']='application/json'
    req=request.Request(BASE+path,data=data,headers=headers,method=method)
    try:
        with request.build_opener(NoRedirect()).open(req,timeout=30) as res:
            raw=res.read(MAX_JSON+1)
            if len(raw)>MAX_JSON: raise ApiError('Risposta Fourthwall troppo grande.')
            if not raw: return {}
            return json.loads(raw)
    except error.HTTPError as exc:
        messages={400:'Dati non accettati da Fourthwall.',401:'Credenziali API non accettate.',403:'Permessi API insufficienti.',404:'Elemento Fourthwall non trovato.',429:'Limite Fourthwall raggiunto: attendi e riprova.'}
        raise ApiError(messages.get(exc.code, f'Errore Fourthwall HTTP {exc.code}.')) from None
    except (error.URLError,TimeoutError,OSError,json.JSONDecodeError):
        raise ApiError('Connessione a Fourthwall non riuscita.') from None

def list_templates(max_pages=20):
    found=[]
    total=None
    for page in range(1,max_pages+1):
        data=_json_call('GET',f'/product-templates/page/{page}',public=True)
        rows=data.get('results') if isinstance(data,dict) else None
        if not isinstance(rows,list): raise ApiError('Catalogo modelli non riconosciuto.')
        for row in rows:
            if isinstance(row,dict) and row.get('productId') and row.get('name') and row.get('supportsBackendRendering'):
                found.append(row)
        total=data.get('total',total)
        if not rows or (isinstance(total,int) and len(found)>=total): break
    return found

def template_details(product_id):
    if not isinstance(product_id,str) or not product_id.startswith('pro_'): raise ApiError('Modello non valido.')
    data=_json_call('GET','/product-templates/'+parse.quote(product_id,safe=''),public=True)
    areas=data.get('customizableAreas',[]) if isinstance(data,dict) else []
    areas=[a for a in areas if isinstance(a,dict) and a.get('available') and a.get('supportsBackendRendering') and a.get('regionId')]
    if not areas: raise ApiError('Questo modello non supporta la creazione automatica.')
    return data, areas[0]['regionId']

def image_dimensions(path):
    path=Path(path)
    with path.open('rb') as f:
        head=f.read(24)
        if head.startswith(b'\x89PNG\r\n\x1a\n') and len(head)>=24:
            return struct.unpack('>II',head[16:24])
        if head[:2]==b'\xff\xd8':
            f.seek(2)
            while True:
                marker=f.read(1)
                while marker==b'\xff': marker=f.read(1)
                if not marker: break
                code=marker[0]
                if code in (0xD8,0xD9): continue
                size_b=f.read(2)
                if len(size_b)!=2: break
                size=struct.unpack('>H',size_b)[0]
                if size<2: break
                if code in {0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF}:
                    block=f.read(5)
                    if len(block)!=5: break
                    h,w=struct.unpack('>HH',block[1:5]); return w,h
                f.seek(size-2,1)
    raise ApiError('Per ora le bozze accettano immagini JPG o PNG valide.')

def _mime(path):
    ext=Path(path).suffix.lower()
    if ext in ('.jpg','.jpeg'): return 'image/jpeg'
    if ext=='.png': return 'image/png'
    raise ApiError('Per ora la creazione delle bozze accetta JPG e PNG.')

def upload_image(path,user,password):
    path=Path(path); size=path.stat().st_size; content_type=_mime(path)
    width,height=image_dimensions(path)
    slot=_json_call('POST','/media/upload-url',user,password,{'fileName':path.name,'contentType':content_type,'size':size})
    upload_url,file_url=slot.get('uploadUrl'),slot.get('fileUrl')
    upload=parse.urlparse(upload_url or ''); remote=parse.urlparse(file_url or '')
    if upload.scheme!='https' or not upload.hostname or not (upload.hostname=='googleapis.com' or upload.hostname.endswith('.googleapis.com')):
        raise ApiError('Indirizzo di caricamento non riconosciuto.')
    # fileUrl is returned by Fourthwall and can use a separate CDN/storage host.
    # It is sent back only to Fourthwall; this program never downloads from it.
    if remote.scheme != 'https' or not remote.hostname or remote.username or remote.password or remote.fragment:
        raise ApiError('Indirizzo del file Fourthwall non riconosciuto.')
    req=request.Request(upload_url,data=path.read_bytes(),method='PUT',headers={'Content-Type':content_type,'x-goog-content-length-range':f'0,{size}'})
    try:
        with request.build_opener(NoRedirect()).open(req,timeout=120) as res:
            if res.status not in (200,201): raise ApiError('Caricamento immagine non riuscito.')
    except (error.HTTPError,error.URLError,TimeoutError,OSError):
        raise ApiError('Caricamento immagine non riuscito.') from None
    saved=_json_call('POST','/media/images',user,password,{'fileUrl':file_url,'width':width,'height':height})
    image_id=saved.get('id') if isinstance(saved,dict) else None
    if not image_id: raise ApiError('Fourthwall non ha restituito l’ID immagine.')
    return image_id

def create_hidden_draft(user,password,template_id,region,image_id,name,description,profit_margin,sizes=None):
    payload={'type':'design','productTemplateId':template_id,'name':name,'description':description,
             'regions':[{'region':region,'imageId':image_id,'placementStrategy':'AUTO'}],
             'profitMargin':float(profit_margin),'publishOnCreate':False}
    if sizes: payload['sizes']=list(sizes)
    data=_json_call('POST','/products',user,password,payload)
    product_id=data.get('productId') if isinstance(data,dict) else None
    if not product_id: raise ApiError('Bozza creata senza ID riconoscibile.')
    return product_id

def archive_product(user,password,product_id):
    if not isinstance(product_id,str) or not product_id or any(c in product_id for c in '/?#'):
        raise ApiError('ID prodotto non valido.')
    _json_call('DELETE','/products/'+parse.quote(product_id,safe=''),user,password)

def set_product_available(user,password,product_id,available):
    if not isinstance(product_id,str) or not product_id or any(c in product_id for c in '/?#'):
        raise ApiError('ID prodotto non valido.')
    return _json_call('PUT','/products/'+parse.quote(product_id,safe='')+'/availability',
                      user,password,{'available':bool(available)})

def get_product_access(user,password,product_id):
    """Read the storefront visibility, not the independent sold-out flag."""
    if not isinstance(product_id,str) or not product_id or any(c in product_id for c in '/?#'):
        raise ApiError('ID prodotto non valido.')
    data = _json_call('GET','/products/'+parse.quote(product_id,safe=''),user,password)
    access = data.get('access') if isinstance(data,dict) else None
    state = access.get('type') if isinstance(access,dict) else None
    if state not in ('PUBLIC','HIDDEN','PRIVATE','ARCHIVED'):
        raise ApiError('Visibilità del prodotto non riconosciuta; nessuna modifica eseguita.')
    return state

def set_product_public(user,password,product_id):
    """Make a hidden offer visible; availability is a different setting."""
    if not isinstance(product_id,str) or not product_id or any(c in product_id for c in '/?#'):
        raise ApiError('ID prodotto non valido.')
    data = _json_call('PUT','/products/'+parse.quote(product_id,safe='')+'/state',
                      user,password,{'state':'PUBLIC'})
    access = data.get('access') if isinstance(data,dict) else None
    if not isinstance(access,dict) or access.get('type') != 'PUBLIC':
        raise ApiError('Fourthwall non ha confermato la pubblicazione; verifica il prodotto.')
    return data

def create_collection(user,password,name,description):
    data=_json_call('POST','/collections',user,password,{
        'name':name,'description':description,'offerIds':[]})
    collection_id=data.get('id') if isinstance(data,dict) else None
    if not isinstance(collection_id,str) or not collection_id.startswith('col_'):
        raise ApiError('Fourthwall non ha restituito l’ID della collezione.')
    return collection_id,data.get('slug','')

def _collection_path(collection_id,suffix):
    if not isinstance(collection_id,str) or not collection_id.startswith('col_') or any(c in collection_id for c in '/?#'):
        raise ApiError('ID collezione non valido.')
    return '/collections/'+parse.quote(collection_id,safe='')+suffix

def set_collection_available(user,password,collection_id,available):
    return _json_call('PUT',_collection_path(collection_id,'/availability'),user,password,{'available':bool(available)})

def set_collection_products(user,password,collection_id,product_ids):
    ids=list(product_ids)
    if not ids or any(not isinstance(value,str) or not value for value in ids):
        raise ApiError('Prodotti della collezione non validi.')
    return _json_call('PUT',_collection_path(collection_id,'/products'),user,password,{'offerIds':ids})
