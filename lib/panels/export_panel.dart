import 'dart:io';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:flutter/foundation.dart' show kIsWeb;
import '../../services/backend_service.dart';

class ExportPanel extends StatefulWidget {
  final List<Map<String, dynamic>> scanData;
  final String? scanId;
  final Map<String, String>? leftResult;
  final Map<String, String>? rightResult;
  final Map<String, String>? combinedResult;

  const ExportPanel({
    super.key,
    required this.scanData,
    this.scanId,
    this.leftResult,
    this.rightResult,
    this.combinedResult,
  });

  @override
  State<ExportPanel> createState() => _ExportPanelState();
}

class _ExportPanelState extends State<ExportPanel> {
  final TextEditingController _nameController = TextEditingController();
  final TextEditingController _emailController = TextEditingController();
  bool _isExporting = false;

  @override
  void dispose() {
    _nameController.dispose();
    _emailController.dispose();
    super.dispose();
  }

  Future<void> _generateAndEmailPDF() async {
    if (widget.scanData.length < 2 || widget.scanId == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Please complete both scans first.')));
      return;
    }
    if (_emailController.text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Please enter a recipient email address.')));
      return;
    }

    setState(() => _isExporting = true);

    try {
      final pdf = pw.Document();
      final leftScan = widget.scanData.firstWhere((s) => s['side'] == 'Left', orElse: () => {});
      final rightScan = widget.scanData.firstWhere((s) => s['side'] == 'Right', orElse: () => {});

      pw.MemoryImage? leftImg, rightImg;
      if (leftScan.isNotEmpty && leftScan['image'].path.isNotEmpty) leftImg = pw.MemoryImage(await leftScan['image'].readAsBytes());
      if (rightScan.isNotEmpty && rightScan['image'].path.isNotEmpty) rightImg = pw.MemoryImage(await rightScan['image'].readAsBytes());

      pdf.addPage(
        pw.MultiPage(
          pageFormat: PdfPageFormat.a4,
          build: (pw.Context context) {
            return [
              pw.Header(level: 0, child: pw.Text('ATLAS-BC Medical Report', style: pw.TextStyle(fontSize: 24, fontWeight: pw.FontWeight.bold))),
              pw.Text('Scan ID: ${widget.scanId}'),
              pw.Text('Date: ${DateTime.now().toString().split('.')[0]}'),
              pw.Text('Physician: ${_nameController.text.isEmpty ? 'Not Provided' : _nameController.text}'),
              pw.SizedBox(height: 20),

              // Section 1: Left Breast
              pw.Text('1. Left Breast Analysis (${leftScan['view'] ?? 'N/A'})', style: pw.TextStyle(fontSize: 16, fontWeight: pw.FontWeight.bold)),
              pw.SizedBox(height: 10),
              if (leftImg != null) pw.Container(height: 150, child: pw.Image(leftImg)) else pw.Text('[Simulated Image Placeholder]'),
              pw.SizedBox(height: 10),
              pw.Text('Classification: ${widget.leftResult?['classification'] ?? '--'}'),
              pw.Text('Assessment: ${widget.leftResult?['recommendation'] ?? '--'}'),
              pw.SizedBox(height: 30),

              // Section 2: Right Breast
              pw.Text('2. Right Breast Analysis (${rightScan['view'] ?? 'N/A'})', style: pw.TextStyle(fontSize: 16, fontWeight: pw.FontWeight.bold)),
              pw.SizedBox(height: 10),
              if (rightImg != null) pw.Container(height: 150, child: pw.Image(rightImg)) else pw.Text('[Simulated Image Placeholder]'),
              pw.SizedBox(height: 10),
              pw.Text('Classification: ${widget.rightResult?['classification'] ?? '--'}'),
              pw.Text('Assessment: ${widget.rightResult?['recommendation'] ?? '--'}'),
              pw.SizedBox(height: 30),

              // Section 3: Combined Result
              pw.Container(
                padding: const pw.EdgeInsets.all(10),
                decoration: pw.BoxDecoration(border: pw.Border.all(color: PdfColors.teal)),
                child: pw.Column(
                  crossAxisAlignment: pw.CrossAxisAlignment.start,
                  children: [
                    pw.Text('3. Combined Final AI Assessment', style: pw.TextStyle(fontSize: 18, fontWeight: pw.FontWeight.bold, color: PdfColors.teal)),
                    pw.Divider(),
                    pw.Text('Overall Classification: ${widget.combinedResult?['classification'] ?? '--'}'),
                    pw.Text('Overall Confidence: ${widget.combinedResult?['confidence'] ?? '--'}'),
                    pw.SizedBox(height: 10),
                    pw.Text('Final Recommendation:', style: pw.TextStyle(fontWeight: pw.FontWeight.bold)),
                    pw.Text(widget.combinedResult?['recommendation'] ?? '--'),
                  ]
                )
              )
            ];
          },
        ),
      );

      String localPath = '';
      if (!kIsWeb) {
        final outputDir = await getApplicationDocumentsDirectory();
        final file = File('${outputDir.path}/${widget.scanId}_Report.pdf');
        await file.writeAsBytes(await pdf.save());
        localPath = file.path;
      }

      await BackendService.sendEmailReport(emailAddress: _emailController.text, pdfFilePath: localPath, scanId: widget.scanId!);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Report successfully sent to ${_emailController.text}'), backgroundColor: const Color(0xFF0D9488)),
        );
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e'), backgroundColor: const Color(0xFFE11D48)));
    } finally {
      if (mounted) setState(() => _isExporting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text('Automated Report Delivery', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: Color(0xFF0F172A))),
          const SizedBox(height: 8),
          const Text('Generates a 3-part PDF (Left, Right, Combined) and automatically sends it to the provided email address.', style: TextStyle(color: Color(0xFF64748B))),
          const SizedBox(height: 24),
          
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: const Color(0xFFE2E8F0))),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Physician Name (Voluntary)', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Color(0xFF475569))),
                const SizedBox(height: 8),
                TextField(controller: _nameController, decoration: const InputDecoration(hintText: 'e.g. Dr. Jane Smith', border: OutlineInputBorder(), contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 12))),
                const SizedBox(height: 16),
                const Text('Recipient Email Address', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Color(0xFF475569))),
                const SizedBox(height: 8),
                TextField(controller: _emailController, keyboardType: TextInputType.emailAddress, decoration: const InputDecoration(hintText: 'doctor@hospital.com', border: OutlineInputBorder(), contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 12))),
              ],
            ),
          ),
          const SizedBox(height: 48),

          ElevatedButton.icon(
            icon: _isExporting ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2)) : const Icon(Icons.send, color: Colors.white),
            label: Text(_isExporting ? 'Sending Report...' : 'Generate & Send Report', style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0D9488), padding: const EdgeInsets.symmetric(vertical: 16), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8))),
            onPressed: _isExporting ? null : _generateAndEmailPDF,
          ),
        ],
      ),
    );
  }
}