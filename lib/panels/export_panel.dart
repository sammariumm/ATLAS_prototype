import 'dart:io';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import '../services/backend_service.dart';

class ExportPanel extends StatefulWidget {
  /// The four views of the exam in the order Left CC, Left MLO, Right CC, Right MLO (empty until the AI has run).
  final List<Map<String, dynamic>> scanData;
  final String? scanId;
  final Map<String, String>? leftResult;  // null = left breast not available
  final Map<String, String>? rightResult; // null = right breast not available
  final Map<String, String>? combinedResult;
  final String note;
  final VoidCallback onNewPatient;

  const ExportPanel({
    super.key,
    required this.scanData,
    this.scanId,
    this.leftResult,
    this.rightResult,
    this.combinedResult,
    this.note = '',
    required this.onNewPatient,
  });

  @override
  State<ExportPanel> createState() => _ExportPanelState();
}

class _ExportPanelState extends State<ExportPanel> {
  final TextEditingController _emailController = TextEditingController();
  bool _isGeneratingPDF = false;
  bool _isSendingEmail = false;
  String? _savedPdfPath;

  bool get _hasResult => widget.combinedResult != null && widget.scanData.isNotEmpty;

  @override
  void didUpdateWidget(ExportPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    // A new analysis makes a PDF that was generated earlier out of date: it must be generated again before emailing.
    if (!identical(oldWidget.combinedResult, widget.combinedResult) ||
        !identical(oldWidget.leftResult, widget.leftResult) ||
        !identical(oldWidget.rightResult, widget.rightResult)) {
      _savedPdfPath = null;
    }
  }

  @override
  void dispose() {
    _emailController.dispose();
    super.dispose();
  }

  /// The picture put in the PDF: the JPEG preview (the PDF library cannot read 16-bit PNGs), else the PNG.
  String _pdfImagePath(Map<String, dynamic> scan) {
    final String preview = (scan['preview_path'] ?? '').toString();
    if (preview.isNotEmpty) return preview;
    return (scan['image_path'] ?? '').toString();
  }

  /// One picture box of the report: the label, then the picture, or a grey "NOT AVAILABLE" box.
  pw.Widget _pdfViewBox(String label, pw.MemoryImage? image) {
    return pw.Expanded(
      child: pw.Column(
        crossAxisAlignment: pw.CrossAxisAlignment.start,
        children: [
          pw.Text(label, style: const pw.TextStyle(fontWeight: pw.FontWeight.bold, fontSize: 11)),
          pw.SizedBox(height: 4),
          pw.Container(
            height: 180,
            alignment: pw.Alignment.center,
            decoration: const pw.BoxDecoration(color: PdfColors.grey200),
            child: image != null
                ? pw.Image(image, fit: pw.BoxFit.contain)
                : pw.Text('NOT AVAILABLE', style: const pw.TextStyle(fontSize: 11, color: PdfColors.grey700)),
          ),
        ],
      ),
    );
  }

  /// One breast: its result and its two views.
  pw.Widget _pdfBreastSection(String side, Map<String, String>? result, Map<String, pw.MemoryImage> images) {
    return pw.Column(
      crossAxisAlignment: pw.CrossAxisAlignment.start,
      children: [
        pw.Text('${side.toUpperCase()} BREAST', style: const pw.TextStyle(fontSize: 16, fontWeight: pw.FontWeight.bold)),
        pw.Divider(),
        pw.Text(
          result != null
              ? 'Result: ${result['classification'] ?? 'N/A'}     Confidence: ${result['confidence'] ?? 'N/A'}'
              : 'Not available: no image of this breast was provided.',
        ),
        pw.SizedBox(height: 8),
        pw.Row(
          crossAxisAlignment: pw.CrossAxisAlignment.start,
          children: [
            _pdfViewBox('$side CC', images['$side-CC']),
            pw.SizedBox(width: 16),
            _pdfViewBox('$side MLO', images['$side-MLO']),
          ],
        ),
      ],
    );
  }

  Future<void> _generatePDF() async {
    if (!_hasResult || widget.scanId == null) return;
    setState(() => _isGeneratingPDF = true);

    try {
      final pdf = pw.Document();

      // 1. Load the pictures that exist. A view marked "not available" has no picture (and a picture that
      //    cannot be read is left out instead of stopping the whole report).
      final Map<String, pw.MemoryImage> images = {};
      for (final scan in widget.scanData) {
        final String path = _pdfImagePath(scan);
        if (scan['status'] != 'captured' || path.isEmpty) continue;
        try {
          images['${scan['side']}-${scan['view']}'] = pw.MemoryImage(File(path).readAsBytesSync());
        } catch (e) {
          debugPrint('Could not add $path to the PDF: $e');
        }
      }

      final String basis = widget.combinedResult?['basis'] ?? '';

      pdf.addPage(
        pw.MultiPage(
          pageFormat: PdfPageFormat.a4,
          build: (context) => [
            pw.Header(level: 0, child: pw.Text('ATLAS-BC: Mammography Analysis', style: const pw.TextStyle(fontSize: 24, fontWeight: pw.FontWeight.bold))),
            pw.Text('Scan ID: ${widget.scanId} | Date: ${DateTime.now().toString().split('.')[0]}'),
            pw.SizedBox(height: 16),

            pw.Container(
              padding: const pw.EdgeInsets.all(12),
              color: PdfColors.grey200,
              child: pw.Column(
                crossAxisAlignment: pw.CrossAxisAlignment.start,
                children: [
                  pw.Text('OVERALL BILATERAL DIAGNOSIS', style: const pw.TextStyle(fontSize: 14, fontWeight: pw.FontWeight.bold)),
                  pw.SizedBox(height: 8),
                  pw.Text('Classification: ${widget.combinedResult?['classification'] ?? 'N/A'}', style: const pw.TextStyle(fontSize: 22, color: PdfColors.red800, fontWeight: pw.FontWeight.bold)),
                  pw.Text('Confidence: ${widget.combinedResult?['confidence'] ?? 'N/A'}'),
                  if (basis.isNotEmpty) pw.Text('Based on: $basis'),
                ]
              )
            ),
            if (widget.note.isNotEmpty) ...[
              pw.SizedBox(height: 8),
              pw.Text('Note: ${widget.note}', style: const pw.TextStyle(fontSize: 11)),
            ],
            pw.SizedBox(height: 16),

            _pdfBreastSection('Left', widget.leftResult, images),
            pw.SizedBox(height: 16),
            _pdfBreastSection('Right', widget.rightResult, images),
            pw.SizedBox(height: 24),

            pw.Text('Patient Next Steps', style: const pw.TextStyle(fontSize: 18, fontWeight: pw.FontWeight.bold)),
            pw.Divider(),
            pw.Text(widget.combinedResult?['recommendation'] ?? 'Consult healthcare provider for further evaluation.', style: const pw.TextStyle(fontSize: 14)),
          ],
        ),
      );

      final outputDir = await getApplicationDocumentsDirectory();
      final file = File('${outputDir.path}/ATLAS_${widget.scanId}.pdf');
      await file.writeAsBytes(await pdf.save());

      if (mounted) setState(() => _savedPdfPath = file.path);

      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('PDF Saved: ${file.path}'), backgroundColor: const Color(0xFF0D9488)));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e'), backgroundColor: Colors.red));
    } finally {
      if (mounted) setState(() => _isGeneratingPDF = false);
    }
  }

  Future<void> _sendEmail() async {
    if (_emailController.text.isEmpty || _savedPdfPath == null) return;
    setState(() => _isSendingEmail = true);

    try {
      await BackendService.sendEmailReport(emailAddress: _emailController.text, pdfFilePath: _savedPdfPath!, scanId: widget.scanId!);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Email Sent Successfully!'), backgroundColor: Color(0xFF0D9488)));
        _emailController.clear();
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e'), backgroundColor: Colors.red));
    } finally {
      if (mounted) setState(() => _isSendingEmail = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final bool canGenerate = _hasResult && widget.scanId != null;

    return Padding(
      padding: const EdgeInsets.all(12.0),
      child: Column(
        children: [
          Expanded(
            flex: 4,
            child: Container(
              padding: const EdgeInsets.all(16.0),
              decoration: BoxDecoration(color: const Color(0xFF1E293B), borderRadius: BorderRadius.circular(12)),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(Icons.picture_as_pdf, size: 40, color: Colors.white),
                  const SizedBox(height: 8),
                  Text('Report: ${widget.scanId ?? 'Pending'}', textAlign: TextAlign.center, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 4),
                  Text(
                    _savedPdfPath != null ? 'PDF Generated' : (_hasResult ? 'Data Ready' : 'Waiting for the analysis'),
                    textAlign: TextAlign.center,
                    style: TextStyle(color: _savedPdfPath != null ? const Color(0xFF0D9488) : Colors.white54, fontSize: 14),
                  ),
                  const Spacer(),
                  ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0D9488), padding: const EdgeInsets.symmetric(vertical: 16)),
                    onPressed: (canGenerate && !_isGeneratingPDF) ? _generatePDF : null,
                    icon: _isGeneratingPDF ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white)) : const Icon(Icons.download, color: Colors.white, size: 20),
                    label: const Text('GENERATE PDF', style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.bold)),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Expanded(
            flex: 4,
            child: Container(
              padding: const EdgeInsets.all(16.0),
              decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: Colors.grey.shade300)),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text('Email Report', style: TextStyle(color: Color(0xFF0F172A), fontSize: 16, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _emailController,
                    keyboardType: TextInputType.emailAddress,
                    style: const TextStyle(fontSize: 14),
                    decoration: InputDecoration(
                      labelText: 'Email Address',
                      labelStyle: const TextStyle(fontSize: 14),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                      prefixIcon: const Icon(Icons.email, size: 20),
                      contentPadding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                  ),
                  const Spacer(),
                  ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0F172A), padding: const EdgeInsets.symmetric(vertical: 16)),
                    onPressed: (_savedPdfPath != null && !_isSendingEmail) ? _sendEmail : null,
                    icon: _isSendingEmail ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white)) : const Icon(Icons.send, color: Colors.white, size: 20),
                    label: const Text('SEND EMAIL', style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.bold)),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),

          // NEW: BIG Reset Button at the bottom
          ElevatedButton.icon(
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.amber.shade700,
              padding: const EdgeInsets.symmetric(vertical: 24),
              minimumSize: const Size(double.infinity, 60),
            ),
            onPressed: widget.onNewPatient, // Triggers global reset
            icon: const Icon(Icons.person_add, color: Colors.black, size: 24),
            label: const Text('FINISH & START NEW PATIENT', style: TextStyle(color: Colors.black, fontSize: 16, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }
}
