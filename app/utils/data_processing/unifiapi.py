from dataclasses import dataclass, field, fields
from typing import Optional
from google.protobuf.internal.decoder import _DecodeVarint as decodeVarint
from typing import ForwardRef
import datetime
import requests
import struct
import uuid

from .spectrumdatalist_pb2 import SpectrumData2D

def decode_spectra(data: bytes) -> list[Spectrum]:
    spectra = []
    pos, next_pos = 0, 0
    while pos < len(data):
        msg = SpectrumData2D()
        next_pos, pos = decodeVarint(data, pos)
        msg.ParseFromString(data[pos:pos+next_pos])
        pos += next_pos
        spec = Spectrum(decode_guid(msg.Id.lo, msg.Id.hi),
                        msg.ValuesX, msg.ValuesY,
                        msg.SpectrumData3D.RetentionTime,
                        msg.SpectrumData3D.RetentionTimeIndex,
                        msg.SpectrumData3D.TotalNumberOfSpectra)
        spectra.append(spec)
    return spectra

def reverse_string(s: str, start:int=0, end:int=0) -> str:
    return "".join(reversed([s[i:i+2] for i in range(start, end+2, 2)]))

def decode_guid(low: int, high: int) -> str:
    high, low = struct.pack("<Q", high), struct.pack("<Q", low)
    return str(uuid.UUID(bytes_le=low+high))


class CheckDataTypeMixin:
    
    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            try:
                if isinstance(f.type, ForwardRef):
                    continue
                if f.type.__name__ == 'list':
                    if len(f.type.__args__) == 1:
                        t = f.type.__args__[0]
                        if t == IonResponse:
                            value = [t(**v) if not isinstance(v,t) else v for v in value]
                            setattr(self, f.name, value)
                else:
                    if not isinstance(value, f.type):
                        if f.type == datetime.datetime and value is not None:
                                setattr(self, f.name, datetime.datetime.fromisoformat(value))
                        elif f.type in (Method, Status, Sample, IonResponse,
                                        ADCGroup, TOFGroup, AnalyticalTechnique,
                                        Axis):
                            value.pop('@odata.context', None)
                            value.pop('@odata.type', None)
                            setattr(self, f.name, f.type(**value))
            except AttributeError:
                print(f.type, isinstance(f.type, ForwardRef))

#  'AnalysisMethod',
#  'Report',
#  'ReportTemplate',
#  'SampleList',
#  'Unknown'}
        
@dataclass
class Folder:
    api: UNIFIAPI = field(repr=False)
    id : str
    name: str
    path : str
    folderType: str
    parentId: str

    def items(self, skip: int = 0, top: int = None):
        url = f'folders({self.id})/items?$skip={skip}'
        if top is not None:
            url += f'&$top={top}'
        
        results = self.api.call(url)
        return [Item(self.api, **r) for r in results.get('value', [])]

    def subfolders(self):
        results = self.api.call(f'folders({self.id})/subfolders')
        return [Folder(self.api, **r) for r in results.get('value', [])]

    def parent(self):
        result = self.api.call(f'folders({self.id})/parent')
        return Folder(self.api, **result)

@dataclass
class Item(CheckDataTypeMixin):
    api: UNIFIAPI = field(repr=False)
    id : str
    name: str
    description: str
    type: str
    idInFolder: int
    autoExportStatus: str
    version: int
    createdAt: datetime.datetime
    creatorFullName: str
    modifiedAt: datetime.datetime
    modifierFullName: str
    dataOnline: bool
    imported: bool
    status: str
    lockedByFullName: str
    restoredAt: datetime.datetime
    restoredByFullName: str
    dataType: str
    remark: str
    summary: str

    def folder(self):
        result = self.api.call(f'items({self.id})/folder')
        return Folder(self.api, **result)

    def convert(self):
        mapping = {'SampleResult': 'sampleresults',
                   'SampleData': 'sampledata',
                   'Analysis': 'analyses',
                   'SampleSet': 'samplesets'
                   #'SampleList': ?
                  }
        endpoint = mapping.get(self.type)
        
        if endpoint is None:
            raise ValueError("Unknown Item Type")

        item_type = eval(self.type)
            
        return item_type(self.api, **self.api.call(f"{endpoint}({self.id})"))

@dataclass
class Status:
    limitStatus: str
    manuallyModified: bool
    sampleAltered: bool

@dataclass
class Method:
    methodId: str
    name: str
    description: str
    version: int

@dataclass
class Analysis(CheckDataTypeMixin):
    api: UNIFIAPI = field(repr=False)
    id: str
    name: str
    description: str
    status: Status
    method: Method

    def folder(self):
        result = self.api.call(f'analyses({self.id})/folder')
        return Folder(self.api, **result)

    def samplesets(self):
        results = self.api.call(f'analyses({self.id})/samplesets')
        return [SampleSet(self.api, **r) for r in results.get('value', [])]

    def sampleresults(self):
        results = self.api.call(f'analyses({self.id})/sampleresults')
        return [SampleResult(self.api, **r) for r in results.get('value', [])]

@dataclass
class SampleSet:
    api: UNIFIAPI = field(repr=False)
    id: str
    name: str
    description: str

@dataclass
class Sample:
    description: str
    originalSampleId: str
    id: str
    gender: str
    name: str
    assayConditions: str
    bracketGroup: str
    dose: str
    dosingRoute:str
    eCordId: str
    day: str
    experimentalConcentration: str
    groupId: str
    injectionId: str
    matrix: str
    solventDelay: int
    species: str
    studyId: str
    subjectId: str
    molForm: str
    preparation: str
    sampleType: str
    batchId: str
    studyName: str
    sampleLevel: str
    sampleWeight: int
    dilution: int
    replicateNumber: int
    wellPosition: str
    injectionVolume: int
    acquisitionRunTime: str
    acquisitionStartTime: datetime.datetime
    time: str
    processingOptions: str
    processingFunction: str
    processingSequenceNumber: int

@dataclass
class SampleResult(CheckDataTypeMixin):
    api: UNIFIAPI = field(repr=False)
    id: str
    name: str
    description: str
    sample: Sample

    def folder(self):
        result = self.api.call(f'sampleresults({self.id})/folder')
        return Folder(self.api, **result)

    def sampledata(self):
        results = self.api.call(f'sampleresults({self.id})/sampledata')
        return [SampleData(self.api, **r) for r in results.get('value', [])]

    def analyses(self):
        results = self.api.call(f'sampleresults({self.id})/analyses')
        return [Analysis(self.api, **r) for r in results.get('value', [])]

    def spectruminfos(self):
        results = self.api.call(f'sampleresults({self.id})/spectruminfos')
        return [SpectrumInfos(self.api, self, **r) for r in results.get('value', [])]

@dataclass
class SampleData(CheckDataTypeMixin):
    api: UNIFIAPI = field(repr=False)
    id: str
    name: str
    description: str
    sample: Sample

    def folder(self):
        result = self.api.call(f'sampledata({self.id})/folder')
        return Folder(self.api, **result)

    def sampleset(self):
        result = self.api.call(f'sampledata({self.id})/sampleset')
        return SampleSet(self.api, **result)

    def sampleresults(self):
        results = self.api.call(f'sampledata({self.id})/sampleresults')
        return [SampleResult(self.api, **r) for r in results.get('value', [])]

@dataclass
class IonResponse:
    ionType: str
    charge: int
    averageIonArea: float

@dataclass
class ADCGroup(CheckDataTypeMixin):
    acquisitionMode: str
    acquisitionFrequency: str
    ionResponses: list[IonResponse]

@dataclass
class TOFGroup:
    nominalResolution: int
    mseLevel: str
    pusherFrequency: float
    lteff: int
    veff: float
    samplingFrequency: float

@dataclass
class AnalyticalTechnique(CheckDataTypeMixin):
    hardwareName: Optional[str] = None
    scanningMethod: Optional[str] = None
    massAnalyser: Optional[str] = None
    ionisationMode: Optional[str] = None
    ionisationType: Optional[str] = None
    lowMass: Optional[int] = None
    highMass: Optional[int] = None
    adcGroup: Optional[ADCGroup] = None
    tofGroup: Optional[TOFGroup] = None
    quadGroup: Optional[str] = None

@dataclass
class Axis:
    label: str
    unit: str
    lowerBound: int
    upperBound: int
    
@dataclass
class SpectrumInfos(CheckDataTypeMixin):
    api: UNIFIAPI = field(repr=False)
    sampleResult: SampleResult = field(repr=False)
    id: str
    name: str
    isCentroidData: bool
    isRetentionData: bool
    isIonMobilityData: bool
    hasCCSCalibration: bool
    detectorType: str
    analyticalTechnique: AnalyticalTechnique
    axisX: Axis
    axisY: Axis

    def data(self, skip: int = 0, top: int = None, stream: bool = False):
        url = f'sampleresults({self.sampleResult.id})/spectruminfos({self.id})/data?$skip={skip}'
        if top is not None:
            url += f'&$top={top}'
        results = self.api.call(url, stream=stream)

        if stream:
            return decode_spectra(results)
        else:
            value = results.get('value', [])
            data = []
            for r in value:
                r.pop('@odata.type', None)
                data.append(Spectrum(**r))
            return data

@dataclass
class Spectrum:
    id: str
    valuesX: list[int]
    valuesY: list[int]
    retentionTime: float
    retentionTimeIndex: int
    totalNumberOfSpectra: int
        
class UNIFIAPI:
    def __init__(self, address, secret = "secret", certificate = None):
        self.session = requests.Session()
        self.session.verify =  certificate if certificate else False
        self.base_address = f"https://{address}:48505/unifi/v1/"
        self.token_address = f"https://{address}:48333/connect/token"
        self.client_id = "resourceownerclient"
        self.client_secret = secret
        self.scope = "webapi"
        self._token = None

    def connect(self, username: str, password: str):
        data = {
            'grant_type': 'password',
            'username': username,
            'password': password,
            'client_secret': self.client_secret,
            'client_id': self.client_id
        }
        response = self.session.post(self.token_address, data)

        # Got the response, check it is okay
        if response.ok:
            contents = response.json()
            self._token = contents.get('access_token')
            print('Login sucessfull')
        else:
            raise ValueError('Authentication error, Response: ', response.status_code, ' ', response.reason, ' Text: ', response.text )

    def call(self, request_url: str, stream:bool=False):
        header = {'Authorization': 'Bearer ' + self._token}
        if stream:
            header['Accept'] = 'application/octet-stream'

        url = self.base_address + request_url
        if stream:
            with self.session.get(url, headers=header, stream = True) as response:
                result = b''
                for n, chunk in enumerate(response.iter_content(chunk_size=1024*1024), start=1):
                    result += chunk
        else:
            response = self.session.get(url, headers=header)

            if not response.ok:
                if response.status_code == 401: # unauthorised
                    print( 'Clear access_token: ', self._token)
                    
                raise ValueError('Response: ', response.status_code, ' ', response.reason, ' Text: ', response.text )

            result = response.json()
            result.pop('@odata.context', None)
            result.pop('@odata.type', None)
        
        return result

    def get_folders(self):
        results = self.call('folders')
        return [Folder(self, **r) for r in results.get('value', [])]

    def get_folder_by_id(self, folder_id: str):
        result = self.call(f'folders({folder_id})')
        result.pop('@odata.context')
        return Folder(self, **result)

    def get_folder_by_path(self, path: str):
        for folder in self.get_folders():
            if folder.path == path:
                return folder

    def get_item_by_id(self, item_id: str):
        result = self.call(f'items({item_id})')
        return Item(self, **result)

    def get_analysis_by_id(self, analysis_id: str):
        result = self.call(f'analyses({analysis_id})')
        return Analysis(self, **result)

    def get_sampledata_by_id(self, sample_data_id: str):
        result = self.call(f'sampledata({sample_data_id})')
        return SampleData(self, **result)

    def get_sampleresult_by_id(self, sample_result_id: str):
        result = self.call(f'sampleresults({sample_result_id})')
        return SampleResult(self, **result)
