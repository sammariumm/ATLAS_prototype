import 'dart:io';
import 'package:flutter/material.dart';
<<<<<<< Updated upstream
import 'package:flutter/foundation.dart' show kIsWeb;
import '../../services/backend_service.dart';
=======
import '../services/backend_service.dart';
>>>>>>> Stashed changes

class ResultsPanel extends StatefulWidget {
  final List<Map<String, dynamic>> scanData;
  final String? scanId;
  final Map<String, String>? combinedResult;
  final VoidCallback onNewPatient; // NEW 

  const ResultsPanel({
<<<<<<< Updated upstream
    super.key,
    required this.scanData,
    this.scanId,
=======
    super.key, 
    required this.scanData, 
    this.scanId, 
    this.leftResult, 
    this.rightResult, 
>>>>>>> Stashed changes
    this.combinedResult,
    required this.onNewPatient, // NEW
  });

  @override
  State<ResultsPanel> createState() => _ResultsPanelState();
}

class _ResultsPanelState extends State<ResultsPanel> {
  bool? _isAccurate;
  bool _isSubmitting = false;

  void _showEnlargedImage(String path) {
    if (path.isEmpty) return;
    showDialog(
      context: context,
      builder: (context) => Dialog(
        backgroundColor: Colors.black,
        insetPadding: EdgeInsets.zero,
        child: Stack(
          alignment: Alignment.topRight,
          children: [
            SizedBox(width: double.infinity, height: double.infinity, child: Image.file(File(path), fit: BoxFit.contain)),
            Padding(
              padding: const EdgeInsets.all(16.0),
              child: ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: Colors.red, padding: const EdgeInsets.all(16)),
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('CLOSE', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _handleSubmit() async {
    if (_isAccurate == null || widget.scanData.length < 2 || widget.scanId == null) return;
    setState(() => _isSubmitting = true);

    try {
<<<<<<< Updated upstream
      if (_isAccurate == true) {
        await BackendService.sendToBlockchain(
          scanId: widget.scanId!,
          scanData: widget.scanData,
          combinedClassification: widget.combinedResult?['classification'] ?? 'Unknown',
          isAccurate: _isAccurate!,
        );
      }
      await BackendService.saveToDatabase(scanId: widget.scanId!, physicianName: 'Doctor', email: null);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Combined Result submitted!'), backgroundColor: Color(0xFF0D9488)));
    } catch (e) {
      debugPrint('$e');
=======
      await BackendService.saveScanRecord(
        scanId: widget.scanId!,
        scanData: widget.scanData,
        leftResult: widget.leftResult,
        rightResult: widget.rightResult,
        combinedResult: widget.combinedResult,
        isAccurate: _isAccurate!,
      );
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Saved to Database!'), backgroundColor: Color(0xFF0D9488)));
      
      // Auto-move to Export panel upon successful save
      // (The navigation bar handles this manually, but it's safe here)
      
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Database Error'), backgroundColor: Colors.red));
>>>>>>> Stashed changes
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          flex: 4,
          child: Container(
            color: const Color(0xFF1E293B),
            padding: const EdgeInsets.all(8),
            child: Row(
              children: widget.scanData.map((scan) => Expanded(
                child: GestureDetector(
                  onTap: () => _showEnlargedImage(scan['image_path']),
                  child: Container(
                    margin: const EdgeInsets.symmetric(horizontal: 4),
                    decoration: BoxDecoration(color: Colors.black, border: Border.all(color: Colors.grey.shade800), borderRadius: BorderRadius.circular(8)),
                    child: Stack(
                      fit: StackFit.expand,
                      children: [
                        Image.file(File(scan['image_path']), fit: BoxFit.cover),
                        Positioned(
                          bottom: 8, left: 8,
                          child: Container(padding: const EdgeInsets.all(4), color: Colors.black87, child: Text('${scan['side']} ${scan['view']}', style: const TextStyle(color: Colors.white, fontSize: 12))),
                        )
                      ],
                    ),
                  ),
                ),
              )).toList(),
            ),
          ),
        ),
        Expanded(
          flex: 6,
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('COMBINED AI RESULT', style: TextStyle(color: Color(0xFF64748B), fontWeight: FontWeight.bold, fontSize: 14)),
                const SizedBox(height: 8),
                Text(widget.combinedResult?['classification'] ?? '--', style: const TextStyle(color: Color(0xFF0F172A), fontSize: 32, fontWeight: FontWeight.bold)),
                Text('Confidence: ${widget.combinedResult?['confidence'] ?? '--'}', style: const TextStyle(color: Color(0xFF0D9488), fontSize: 18, fontWeight: FontWeight.bold)),
                const SizedBox(height: 12),
                Text(widget.combinedResult?['recommendation'] ?? 'Awaiting Data...', style: const TextStyle(fontSize: 16, color: Color(0xFF0F172A))),
                const Divider(height: 24),
                Row(
                  children: [
                    Expanded(
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: _isAccurate == true ? const Color(0xFF0D9488) : Colors.white, side: const BorderSide(color: Color(0xFF0D9488)), padding: const EdgeInsets.symmetric(vertical: 16)),
                        onPressed: widget.scanData.length < 2 ? null : () => setState(() => _isAccurate = true),
                        child: Text('Accurate', textAlign: TextAlign.center, style: TextStyle(color: _isAccurate == true ? Colors.white : const Color(0xFF0D9488), fontSize: 16)),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(backgroundColor: _isAccurate == false ? const Color(0xFFE11D48) : Colors.white, side: const BorderSide(color: Color(0xFFE11D48)), padding: const EdgeInsets.symmetric(vertical: 16)),
                        onPressed: widget.scanData.length < 2 ? null : () => setState(() => _isAccurate = false),
                        child: Text('Inaccurate', textAlign: TextAlign.center, style: TextStyle(color: _isAccurate == false ? Colors.white : const Color(0xFFE11D48), fontSize: 16)),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                ElevatedButton(
                  style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0F172A), padding: const EdgeInsets.symmetric(vertical: 16)),
                  onPressed: (_isAccurate == null || _isSubmitting || widget.scanData.length < 2) ? null : _handleSubmit,
                  child: _isSubmitting ? const CircularProgressIndicator(color: Colors.white) : const Text('SUBMIT VALIDATION', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                ),
                const SizedBox(height: 12),
                
                // NEW: Discard and Restart Button
                TextButton.icon(
                  style: TextButton.styleFrom(foregroundColor: Colors.red, padding: const EdgeInsets.symmetric(vertical: 16)),
                  onPressed: widget.onNewPatient, // Triggers global reset
                  icon: const Icon(Icons.delete_forever),
                  label: const Text('DISCARD SCAN & RESTART', style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold)),
                )
              ],
            ),
          ),
<<<<<<< Updated upstream
          const SizedBox(height: 16),

          Card(
            elevation: 0, color: Colors.white,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12), side: const BorderSide(color: Color(0xFFE2E8F0))),
            child: Padding(
              padding: const EdgeInsets.all(16.0),
              child: widget.isProcessing
                  ? const Padding(
                      padding: EdgeInsets.all(24.0),
                      child: Center(child: Column(children: [CircularProgressIndicator(color: Color(0xFF0D9488)), SizedBox(height: 16), Text('Analyzing Bilateral Scans...', style: TextStyle(color: Color(0xFF64748B)))])))
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('COMBINED AI ANALYSIS RESULT', style: TextStyle(color: Color(0xFF94A3B8), fontWeight: FontWeight.bold, fontSize: 12)),
                        const SizedBox(height: 12),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Text('Classification', style: TextStyle(color: Color(0xFF64748B), fontSize: 14)),
                                Text(widget.combinedResult?['classification'] ?? '--', style: const TextStyle(color: Color(0xFF0F172A), fontSize: 24, fontWeight: FontWeight.bold)),
                              ],
                            ),
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.end,
                              children: [
                                const Text('Confidence', style: TextStyle(color: Color(0xFF64748B), fontSize: 14)),
                                Text(widget.combinedResult?['confidence'] ?? '--', style: const TextStyle(color: Color(0xFF0D9488), fontSize: 24, fontWeight: FontWeight.bold)),
                              ],
                            ),
                          ],
                        ),
                        const Divider(height: 24),
                        const Text('Next Step Recommendation', style: TextStyle(color: Color(0xFF64748B), fontSize: 12)),
                        const SizedBox(height: 4),
                        Text(widget.combinedResult?['recommendation'] ?? 'N/A', style: const TextStyle(fontSize: 16, color: Color(0xFF0F172A))),
                      ],
                    ),
            ),
          ),
          const SizedBox(height: 16),

          Row(
            children: [
              Expanded(
                child: GestureDetector(
                  onTap: (widget.isProcessing || widget.scanData.length < 2) ? null : () => setState(() => _isAccurate = true),
                  child: Container(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    decoration: BoxDecoration(color: _isAccurate == true ? const Color(0xFFE6FFFA) : Colors.white, border: Border.all(color: _isAccurate == true ? const Color(0xFF0D9488) : const Color(0xFFE2E8F0), width: 2), borderRadius: BorderRadius.circular(8)),
                    child: Column(children: const [Text('Accurate', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Color(0xFF0F172A))), Text('Send to Blockchain', style: TextStyle(color: Color(0xFF0D9488), fontSize: 10))]),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: GestureDetector(
                  onTap: (widget.isProcessing || widget.scanData.length < 2) ? null : () => setState(() => _isAccurate = false),
                  child: Container(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    decoration: BoxDecoration(color: _isAccurate == false ? const Color(0xFFFFF1F2) : Colors.white, border: Border.all(color: _isAccurate == false ? const Color(0xFFE11D48) : const Color(0xFFE2E8F0), width: 2), borderRadius: BorderRadius.circular(8)),
                    child: Column(children: const [Text('Inaccurate', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Color(0xFF0F172A))), Text('Discard Result', style: TextStyle(color: Color(0xFFE11D48), fontSize: 10))]),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 24),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0F172A), padding: const EdgeInsets.symmetric(vertical: 16), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8))),
            onPressed: (_isAccurate == null || widget.isProcessing || widget.scanData.length < 2 || _isSubmitting) ? null : _handleSubmit,
            child: _isSubmitting ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2)) : const Text('Submit Selection', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
          )
        ],
      ),
=======
        ),
      ],
>>>>>>> Stashed changes
    );
  }
}