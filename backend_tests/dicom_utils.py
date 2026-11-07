"""Helpers that write small synthetic DICOM files for the tests."""
import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid


def write_dicom(path, arr, photometric="MONOCHROME2", bits_stored=12, slope=None, intercept=None,
                signed=False, frames=1, compress=None):
    """arr: 2-D integer array (or 3-D frames x rows x cols when frames > 1)."""
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1.2"   # digital mammography, for presentation
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    if int(pydicom.__version__.split(".")[0]) < 3:   # pydicom 3 takes this from the transfer syntax
        ds.is_little_endian = True
        ds.is_implicit_VR = False
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.Modality = "MG"
    ds.PatientName = "Test^Synthetic"
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.Rows, ds.Columns = arr.shape[-2], arr.shape[-1]
    ds.BitsAllocated = 16
    ds.BitsStored = bits_stored
    ds.HighBit = bits_stored - 1
    ds.PixelRepresentation = 1 if signed else 0
    if slope is not None:
        ds.RescaleSlope = slope
    if intercept is not None:
        ds.RescaleIntercept = intercept
    if frames > 1:
        ds.NumberOfFrames = frames
    ds.PixelData = np.ascontiguousarray(arr).astype("<i2" if signed else "<u2").tobytes()
    if compress is not None:
        ds.compress(compress)
    try:
        ds.save_as(str(path), enforce_file_format=True)      # pydicom >= 3
    except TypeError:
        ds.save_as(str(path), write_like_original=False)     # pydicom 2.x
    return ds
